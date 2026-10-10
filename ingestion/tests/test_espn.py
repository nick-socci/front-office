"""Tests for ESPN ingestion: credentials, period completion, and re-fetch rules.

No test here touches the network or reads a real .env. The credential tests assert the
failure message, because an expired-cookie failure is the one a human has to act on.
"""

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from front_office import cli
from front_office.espn import rosters as espn_rosters
from front_office.espn import settings as espn_settings
from front_office.espn.client import EspnCredentials, MissingCredentials
from front_office.http_client import AuthExpired, HttpClient, SourceLimits
from front_office.landing import LandingCollision, LandingZone

LEAGUE_ID = "73677"
SEASON = 2026

# Shape of the mStatus block: latestScoringPeriod is the period currently in progress.
MID_SEASON = {"latestScoringPeriod": 100, "finalScoringPeriod": 180}
SEASON_OVER = {"latestScoringPeriod": 186, "finalScoringPeriod": 180}


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path)


def test_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("ESPN_S2", "cookie-value")
    monkeypatch.setenv("SWID", "{GUID}")
    monkeypatch.setenv("LEAGUE_ID", LEAGUE_ID)
    creds = EspnCredentials.from_env()
    assert creds.league_id == LEAGUE_ID
    assert creds.cookies() == {"espn_s2": "cookie-value", "SWID": "{GUID}"}


def test_missing_credentials_names_what_to_do(monkeypatch):
    monkeypatch.delenv("ESPN_S2", raising=False)
    monkeypatch.setenv("SWID", "{GUID}")
    monkeypatch.setenv("LEAGUE_ID", LEAGUE_ID)
    with pytest.raises(MissingCredentials) as exc:
        EspnCredentials.from_env()
    message = str(exc.value)
    assert "ESPN_S2" in message
    assert ".env" in message


def test_credentials_are_never_included_in_their_repr(monkeypatch):
    """A traceback or log line must not leak a session cookie."""
    creds = EspnCredentials(espn_s2="super-secret", swid="{GUID}", league_id=LEAGUE_ID)
    assert "super-secret" not in repr(creds)
    assert "GUID" not in repr(creds)


def evidence_of(zone, *, season=SEASON, league_id=LEAGUE_ID):
    return espn_rosters.roster_evidence(zone, season=season, league_id=league_id)


def test_roster_needs_fetch_when_never_landed(zone):
    assert espn_rosters.needs_fetch(5, evidence=evidence_of(zone)) is True


def test_in_progress_period_is_refetched_even_when_landed(zone):
    land_roster(zone, period=100, source_status=status_of(100))
    assert espn_rosters.needs_fetch(100, evidence=evidence_of(zone)) is True


def test_refresh_forces_a_refetch(zone):
    land_roster(zone, period=5, source_status=status_of(100))
    assert espn_rosters.needs_fetch(5, evidence=evidence_of(zone), refresh=True) is True


def status_of(latest, final=180):
    return {"latest_scoring_period": latest, "final_scoring_period": final}


def land_roster(
    zone,
    *,
    period,
    stamp="20260901T000000Z",
    source_status=None,
    season=SEASON,
    league_id=LEAGUE_ID,
):
    return zone.write(
        source="espn",
        endpoint="roster",
        partitions={"season": season, "league_id": league_id, "scoring_period": period},
        name=f"fetched_at={stamp}",
        payload={"teams": []},
        request={"url": "https://example.test", "params": {"scoringPeriodId": period}},
        fetched_at=stamp,
        source_status=source_status,
    )


def land_settings(zone, *, stamp, status, season=SEASON, league_id=LEAGUE_ID):
    return zone.write(
        source="espn",
        endpoint="settings",
        partitions={"season": season, "league_id": league_id},
        name=f"fetched_at={stamp}",
        payload={"status": status},
        request={"url": "https://example.test", "params": {"view": "mStatus"}},
        fetched_at=stamp,
    )


def make_client(handler):
    return HttpClient(
        source="espn",
        limits=SourceLimits(min_interval_s=0.0, max_attempts=2, backoff_base_s=0.0),
        transport=httpx.MockTransport(handler),
        sleep=lambda _seconds: None,
    )


def test_settings_lands_a_new_snapshot_on_every_run(zone):
    client = make_client(
        lambda request: httpx.Response(200, json={"settings": {}, "status": MID_SEASON})
    )
    first, _ = espn_settings.backfill_settings(
        zone=zone, client=client, season=SEASON, league_id=LEAGUE_ID, fetched_at="20260101T000000Z"
    )
    second, payload = espn_settings.backfill_settings(
        zone=zone, client=client, season=SEASON, league_id=LEAGUE_ID, fetched_at="20260102T000000Z"
    )
    assert first != second, "settings are a snapshot: history accumulates"
    assert payload["status"] == MID_SEASON
    assert len(list(zone.iter_landed(source="espn", endpoint="settings"))) == 2


def test_roster_backfill_covers_periods_up_to_the_latest(zone):
    requested = []

    def handler(request):
        requested.append(request.url.params.get("scoringPeriodId"))
        return httpx.Response(200, json={"teams": []})

    summary = espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(handler),
        season=SEASON,
        league_id=LEAGUE_ID,
        status={"latestScoringPeriod": 4, "finalScoringPeriod": 180},
        fetched_at="20260101T000000Z",
    )
    assert requested == ["1", "2", "3", "4"]
    assert (summary.fetched, summary.skipped, summary.failed) == (4, 0, 0)


def test_roster_backfill_stops_at_the_final_period_when_the_season_is_over(zone):
    requested = []

    def handler(request):
        requested.append(request.url.params.get("scoringPeriodId"))
        return httpx.Response(200, json={"teams": []})

    espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(handler),
        season=SEASON,
        league_id=LEAGUE_ID,
        status={"latestScoringPeriod": 186, "finalScoringPeriod": 5},
        fetched_at="20260101T000000Z",
    )
    assert requested == ["1", "2", "3", "4", "5"], "periods past the final one do not exist"


def test_roster_backfill_records_the_scoring_period_in_metadata(zone):
    espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(lambda request: httpx.Response(200, json={"teams": []})),
        season=SEASON,
        league_id=LEAGUE_ID,
        status={"latestScoringPeriod": 2, "finalScoringPeriod": 180},
        fetched_at="20260101T000000Z",
    )
    landed = sorted(zone.iter_landed(source="espn", endpoint="roster"), key=lambda r: str(r.path))
    keys = [json.loads((r.path.parent / "meta.json").read_text())["request_key"] for r in landed]
    assert all("scoringPeriodId=" in key for key in keys)


def test_roster_backfill_continues_after_one_period_fails(zone):
    def handler(request):
        if request.url.params.get("scoringPeriodId") == "2":
            return httpx.Response(500)
        return httpx.Response(200, json={"teams": []})

    summary = espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(handler),
        season=SEASON,
        league_id=LEAGUE_ID,
        status={"latestScoringPeriod": 3, "finalScoringPeriod": 180},
        fetched_at="20260101T000000Z",
    )
    assert (summary.fetched, summary.failed) == (2, 1)
    assert summary.failed_periods == [2]


def serve_pro_schedule(monkeypatch):
    """Give `backfill espn` a public client that answers the pro schedule request."""
    monkeypatch.setattr(
        cli,
        "espn_public_client",
        lambda: make_client(
            lambda request: httpx.Response(200, json={"settings": {"proTeams": []}})
        ),
    )


def expires_after_period_one(requested):
    """A handler whose cookies stop working after the first roster request."""

    def handler(request):
        period = request.url.params.get("scoringPeriodId")
        if period is None:  # settings, teams, matchups, transactions
            return httpx.Response(200, json={"status": {"latestScoringPeriod": 5}})
        requested.append(period)
        return httpx.Response(200 if period == "1" else 401, json={"teams": []})

    return handler


def test_roster_backfill_stops_when_authentication_expires(zone):
    requested = []
    with pytest.raises(AuthExpired):
        espn_rosters.backfill_rosters(
            zone=zone,
            client=make_client(expires_after_period_one(requested)),
            season=SEASON,
            league_id=LEAGUE_ID,
            status={"latestScoringPeriod": 5, "finalScoringPeriod": 180},
            fetched_at="20260101T000000Z",
        )
    assert requested == ["1", "2"], "no period after the rejected one is requested"
    assert len(list(zone.iter_landed(source="espn", endpoint="roster"))) == 1


def test_roster_backfill_stops_on_a_collision(zone):
    """Catches a collision counted as one failed period while later periods are fetched."""
    land_roster(zone, period=2, stamp="20260101T000000Z")
    requested = []

    def handler(request):
        requested.append(request.url.params.get("scoringPeriodId"))
        return httpx.Response(200, json={"teams": []})

    with pytest.raises(LandingCollision):
        espn_rosters.backfill_rosters(
            zone=zone,
            client=make_client(handler),
            season=SEASON,
            league_id=LEAGUE_ID,
            status={"latestScoringPeriod": 3, "finalScoringPeriod": 180},
            fetched_at="20260101T000000Z",
            refresh=True,
        )
    assert requested == ["1", "2"], "no period after the collision is requested"


def test_backfill_espn_exits_non_zero_when_authentication_expires(tmp_path, monkeypatch):
    monkeypatch.setenv("ESPN_S2", "s2-cookie-value")
    monkeypatch.setenv("SWID", "{swid-cookie-value}")
    monkeypatch.setenv("LEAGUE_ID", LEAGUE_ID)
    monkeypatch.setattr(cli, "load_env_file", lambda: None)
    serve_pro_schedule(monkeypatch)
    requested = []
    monkeypatch.setattr(
        cli, "espn_client", lambda _credentials: make_client(expires_after_period_one(requested))
    )

    result = CliRunner().invoke(
        cli.app, ["backfill", "espn", "--season", str(SEASON), "--raw-root", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert "cookies expired" in result.output
    assert "Traceback" not in result.output
    assert "cookie-value" not in result.output
    assert requested == ["1", "2"]


def _land_one_roster(zone, response_json, *, run_status=None):
    """Backfill period 1 against a fake roster response; return the landed sidecar."""
    espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(lambda request: httpx.Response(200, json=response_json)),
        season=SEASON,
        league_id=LEAGUE_ID,
        status=run_status or {"latestScoringPeriod": 1, "finalScoringPeriod": 180},
        fetched_at="20260101T000000Z",
    )
    (capture,) = zone.committed(source="espn", endpoint="roster")
    return capture.meta


def test_roster_sidecar_records_the_status_of_the_response_not_of_the_run(zone):
    """Catches the status taken from the run's settings instead of the response it landed (R1.1)."""
    meta = _land_one_roster(
        zone,
        {"teams": [], "status": {"latestScoringPeriod": 101, "finalScoringPeriod": 177}},
        run_status={"latestScoringPeriod": 1, "finalScoringPeriod": 180},
    )
    assert meta["source_status"] == {"latest_scoring_period": 101, "final_scoring_period": 177}


@pytest.mark.parametrize(
    "response",
    [
        {"teams": []},
        {"teams": [], "status": {"latestScoringPeriod": "101", "finalScoringPeriod": 180}},
        {"teams": [], "status": {"latestScoringPeriod": True, "finalScoringPeriod": 180}},
        {"teams": [], "status": [101]},
    ],
    ids=["no status", "string counter", "boolean counter", "status not a mapping"],
)
def test_a_roster_response_without_a_usable_status_still_lands_and_warns(zone, caplog, response):
    """Catches a crash losing the capture, or a non-integer counter recorded as a number (R1.2)."""
    with caplog.at_level("WARNING"):
        meta = _land_one_roster(zone, response)
    assert meta["source_status"]["latest_scoring_period"] is None
    assert any("scoring period 1" in record.getMessage() for record in caplog.records)


# -- the evidence: settled_through, is_closed, is_settled ----------------------------------


def _meta(period, stamp="20260101T000000Z", **status):
    """A roster sidecar as a plain dict; pass source_status=... to include that key."""
    meta = {"partitions": {"season": 2026, "league_id": LEAGUE_ID, "scoring_period": period}}
    meta["fetched_at"] = stamp
    meta.update(status)
    return meta


def _own(latest):
    return {"source_status": {"latest_scoring_period": latest, "final_scoring_period": 180}}


@pytest.mark.parametrize(
    ("latest", "closed"), [(99, False), (100, False), (101, True)], ids=["below", "equal", "above"]
)
def test_a_capture_closes_its_period_only_when_its_own_status_is_past_it(latest, closed):
    """Catches `>=` for `>`: a day still in progress counted as closed (R2.1)."""
    evidence = espn_rosters.settled_through([_meta(100, **_own(latest))], {})
    assert espn_rosters.is_closed(100, evidence) is closed


def test_evidence_at_period_plus_seven_is_closed_not_settled_and_plus_eight_is_settled():
    """Catches an off-by-one in the re-check window (R6.1)."""
    at_seven = espn_rosters.settled_through([_meta(100, **_own(107))], {})
    at_eight = espn_rosters.settled_through([_meta(100, **_own(108))], {})
    assert espn_rosters.RECHECK_PERIODS == 7
    assert espn_rosters.is_closed(100, at_seven)
    assert not espn_rosters.is_settled(100, at_seven)
    assert espn_rosters.is_settled(100, at_eight)


def test_a_newer_capture_with_a_null_status_does_not_unprove_the_period():
    """Catches 'newest capture' used instead of 'some capture' as the evidence (R2.1)."""
    metas = [
        _meta(100, stamp="20260102T000000Z", **_own(108)),
        _meta(100, stamp="20260103T000000Z", source_status={"latest_scoring_period": None}),
    ]
    evidence = espn_rosters.settled_through(metas, {})
    assert espn_rosters.is_closed(100, evidence)
    assert espn_rosters.is_settled(100, evidence)


def test_the_highest_evidence_across_captures_and_periods_is_kept_per_period():
    """Catches evidence mixed up between periods, or the last capture winning over the best."""
    metas = [_meta(100, **_own(105)), _meta(100, **_own(103)), _meta(101, **_own(102))]
    evidence = espn_rosters.settled_through(metas, {})
    assert {period: found.latest for period, found in evidence.items()} == {100: 105, 101: 102}


@pytest.mark.parametrize(
    ("settings_latest", "closed"),
    [(101, True), (100, False), (None, False)],
    ids=["above", "equal", "no entry"],
)
def test_a_legacy_capture_is_judged_by_the_settings_of_its_own_run(settings_latest, closed):
    """Catches legacy captures all trusted, or all refetched (R3.1, R3.2)."""
    by_run = {} if settings_latest is None else {"20260101T000000Z": settings_latest}
    by_run["20260105T000000Z"] = 500  # another run's settings prove nothing here
    evidence = espn_rosters.settled_through([_meta(100)], by_run)
    assert espn_rosters.is_closed(100, evidence) is closed


def test_a_null_source_status_does_not_fall_back_to_the_settings_rule():
    """Catches the fallback papering over a bad status (R3.4)."""
    meta = _meta(100, source_status={"latest_scoring_period": None})
    evidence = espn_rosters.settled_through([meta], {"20260101T000000Z": 200})
    assert not espn_rosters.is_closed(100, evidence)


@pytest.mark.parametrize(
    "value",
    [
        ["a"],
        "101",
        None,
        {},
        {"final_scoring_period": 180},
        {"latest_scoring_period": "101"},
        {"latest_scoring_period": True},
        {"latest_scoring_period": 101.5},
    ],
    ids=[
        "list",
        "string",
        "none",
        "empty",
        "no counter",
        "string counter",
        "bool counter",
        "float",
    ],
)
def test_a_malformed_source_status_is_no_evidence_and_never_an_error(value):
    """Catches one odd sidecar stopping a backfill or the audit, or a non-integer used (R2.2)."""
    evidence = espn_rosters.settled_through(
        [_meta(100, source_status=value)], {"20260101T000000Z": 200}
    )
    assert not espn_rosters.is_closed(100, evidence)
    assert not espn_rosters.is_settled(100, evidence)


def test_a_period_with_no_captures_is_neither_closed_nor_settled():
    """Catches 'never landed' needing a separate branch from 'no evidence'."""
    assert not espn_rosters.is_closed(7, {})
    assert not espn_rosters.is_settled(7, {})


# -- the evidence: a counter that stopped is extended by the calendar (ADR 0047) ----------

BASE = dt.datetime(2026, 10, 1, 6, 0, 0, tzinfo=dt.UTC)


def _stamp(offset):
    """The run stamp of a run `offset` after BASE, in the form the sidecars carry."""
    return (BASE + offset).strftime("%Y%m%dT%H%M%SZ")


def _seen(period, counter, offset):
    """An own-status sidecar of `period` whose counter read `counter`, `offset` after BASE."""
    return _meta(period, stamp=_stamp(offset), **_own(counter))


def test_two_captures_of_one_counter_less_than_a_day_apart_extend_nothing():
    """Catches a span rounded up: 23h59m is not a day, so the answer stays ADR 0018's (R1.3)."""
    metas = [
        _seen(100, 105, dt.timedelta(0)),
        _seen(100, 105, dt.timedelta(hours=23, minutes=59)),
    ]
    evidence = espn_rosters.settled_through(metas, {})[100]
    assert evidence == espn_rosters.PeriodEvidence(latest=105, extended=105)
    assert evidence.unchanged is None


def test_a_counter_seen_unchanged_extends_by_whole_days_and_names_the_counter():
    """Catches a span rounded down to nothing, or `unchanged` left unset when it applies (R1.1)."""
    metas = [
        _seen(100, 105, dt.timedelta(0)),
        _seen(100, 105, dt.timedelta(hours=24)),
        _seen(100, 105, dt.timedelta(hours=72, minutes=1)),
    ]
    evidence = espn_rosters.settled_through(metas, {})[100]
    assert evidence == espn_rosters.PeriodEvidence(latest=105, extended=108, unchanged=105)


def test_a_counter_that_does_not_close_the_period_is_never_extended():
    """Catches extension leaking into the closure of a period still open (R1.4, R1.5)."""
    metas = [_seen(100, 100, dt.timedelta(0)), _seen(100, 100, dt.timedelta(days=30))]
    evidence = espn_rosters.settled_through(metas, {})
    assert evidence[100] == espn_rosters.PeriodEvidence(latest=100, extended=100)
    assert not espn_rosters.is_closed(100, evidence)
    assert not espn_rosters.is_settled(100, evidence)


def test_a_counter_that_closes_the_period_and_stood_for_a_month_settles_it():
    """Catches a stopped counter that closes a period never settling it (R1.4, R1.5)."""
    metas = [_seen(100, 101, dt.timedelta(0)), _seen(100, 101, dt.timedelta(days=30))]
    evidence = espn_rosters.settled_through(metas, {})
    assert espn_rosters.is_closed(100, evidence)
    assert espn_rosters.is_settled(100, evidence)


def test_closure_is_judged_by_the_greatest_counter_and_never_by_the_extended_one():
    """Catches `is_closed` reading `extended`: here extended passes 100 and latest does not."""
    evidence = {100: espn_rosters.PeriodEvidence(latest=100, extended=140, unchanged=100)}
    assert not espn_rosters.is_closed(100, evidence)


def test_a_legacy_and_an_own_status_capture_of_one_counter_a_week_apart_extend_it():
    """Catches the legacy path left out of the sightings (R1.6)."""
    legacy_stamp = _stamp(dt.timedelta(0))
    metas = [_meta(100, stamp=legacy_stamp), _seen(100, 103, dt.timedelta(days=7))]
    evidence = espn_rosters.settled_through(metas, {legacy_stamp: 103})
    assert evidence[100] == espn_rosters.PeriodEvidence(latest=103, extended=110, unchanged=103)
    assert espn_rosters.is_settled(100, evidence)


def test_a_capture_with_no_usable_counter_counts_for_nothing():
    """Catches a null counter taking part in a span, or in `top` (R1.6)."""
    metas = [
        _seen(100, 103, dt.timedelta(0)),
        _meta(
            100,
            stamp=_stamp(dt.timedelta(days=30)),
            source_status={"latest_scoring_period": None},
        ),
    ]
    evidence = espn_rosters.settled_through(metas, {})
    assert evidence[100] == espn_rosters.PeriodEvidence(latest=103, extended=103)


def test_a_counter_with_an_unreadable_stamp_still_closes_and_settles_and_warns(caplog):
    """Catches a bad stamp discarding a usable counter, or passing without a word (R1.6)."""
    metas = [_meta(100, stamp="not-a-stamp", **_own(108))]
    with caplog.at_level("WARNING"):
        evidence = espn_rosters.settled_through(metas, {})
    assert espn_rosters.is_closed(100, evidence)
    assert espn_rosters.is_settled(100, evidence)
    assert any("period 100" in record.getMessage() for record in caplog.records)


def test_an_unreadable_stamp_is_left_out_of_the_span_and_not_counted_as_a_day():
    """Catches an unparsed stamp being treated as the epoch, which would span years (R1.6)."""
    metas = [_seen(100, 105, dt.timedelta(0)), _meta(100, stamp="garbage", **_own(105))]
    evidence = espn_rosters.settled_through(metas, {})
    assert evidence[100] == espn_rosters.PeriodEvidence(latest=105, extended=105)


def test_a_counter_another_response_has_exceeded_is_a_lagging_status_and_not_extended():
    """Catches a lagging status taken for a stopped counter (R1.9)."""
    lagging = [_seen(100, 107, dt.timedelta(0)), _seen(100, 107, dt.timedelta(hours=48))]
    other = _seen(101, 109, dt.timedelta(hours=48))
    with_top = espn_rosters.settled_through([*lagging, other], {})
    assert with_top[100] == espn_rosters.PeriodEvidence(latest=107, extended=107)
    assert not espn_rosters.is_settled(100, with_top)
    alone = espn_rosters.settled_through(lagging, {})
    assert espn_rosters.is_settled(100, alone)


# -- the fetch path: transitions, outages, recovery ----------------------------------------


class Season:
    """A fake league whose roster responses carry a status the test controls, run by run.

    `latest` is what the roster responses say; `overrides` maps a period to a different
    counter (a lagging response). `requested` lists every period asked for, in order.
    """

    def __init__(self, zone, *, final=180):
        self.zone = zone
        self.final = final
        self.requested = []
        self.overrides = {}
        self.runs = 0

    def run(self, latest, *, response_latest=None, refresh=False, run_status=None):
        self.runs += 1
        said = latest if response_latest is None else response_latest
        start = len(self.requested)

        def handler(request):
            period = int(request.url.params["scoringPeriodId"])
            self.requested.append(period)
            counter = self.overrides.get(period, said)
            body = {"teams": [], "status": {"finalScoringPeriod": self.final}}
            if counter is not None:
                body["status"]["latestScoringPeriod"] = counter
            return httpx.Response(200, json=body)

        summary = espn_rosters.backfill_rosters(
            zone=self.zone,
            client=make_client(handler),
            season=SEASON,
            league_id=LEAGUE_ID,
            status=run_status or {"latestScoringPeriod": latest, "finalScoringPeriod": self.final},
            fetched_at=f"20270101T{self.runs:06d}Z",
            refresh=refresh,
        )
        return summary, self.requested[start:]


def test_a_period_is_fetched_on_each_run_through_nine_and_skipped_on_the_tenth(zone):
    """Catches the R1 defect, an off-by-one in the window, or the re-check counted as a failure."""
    season = Season(zone)
    fetched_100 = []
    for latest in range(100, 110):
        summary, requested = season.run(latest)
        fetched_100.append(100 in requested)
        assert summary.unproven == []
        assert summary.failed == 0
    assert fetched_100 == [True] * 9 + [False]


def test_a_mid_day_capture_is_fetched_although_the_run_status_is_past_it(zone):
    """Catches the run's status settling a period whose only capture was taken while it was open."""
    land_roster(zone, period=100, source_status=status_of(100))
    _, requested = Season(zone).run(105)
    assert 100 in requested


def test_an_outage_refetches_every_period_it_spanned(zone):
    """Catches a closed period skipped because a mid-day file exists, or a gap left unfetched."""
    land_roster(zone, period=100, source_status=status_of(100))
    land_roster(zone, period=101, source_status=status_of(101))
    land_roster(zone, period=103, source_status=status_of(103))
    summary, requested = Season(zone).run(105)
    assert [p for p in requested if p >= 100] == [100, 101, 102, 103, 104, 105]
    evidence = evidence_of(zone)
    assert all(espn_rosters.is_closed(p, evidence) for p in range(100, 105))
    assert not espn_rosters.is_closed(105, evidence)
    assert summary.unproven == []


def test_refresh_fetches_a_settled_period(zone):
    """Catches --refresh ignored for settled periods (R2.4)."""
    for period in (1, 2, 3):
        land_roster(zone, period=period, source_status=status_of(100))
    season = Season(zone)
    assert season.run(3)[1] == []
    assert season.run(3, refresh=True)[1] == [1, 2, 3]


def test_a_settled_capture_of_another_league_or_season_settles_nothing_here(zone):
    """Catches cross-league or cross-season leakage of evidence (R2.7)."""
    land_roster(zone, period=5, source_status=status_of(100), league_id="99999")
    land_roster(zone, period=5, source_status=status_of(100), season=2025)
    assert espn_rosters.needs_fetch(5, evidence=evidence_of(zone)) is True
    assert evidence_of(zone) == {}


def test_a_league_id_stored_as_a_number_still_matches(zone):
    """Catches partitions compared without normalising their type."""
    land_roster(zone, period=5, source_status=status_of(100), league_id=int(LEAGUE_ID))
    assert espn_rosters.needs_fetch(5, evidence=evidence_of(zone)) is False


@pytest.mark.parametrize(
    ("settings_latest", "fetch"),
    [(108, False), (107, True), (100, True)],
    ids=["past the window", "inside the window", "at the period"],
)
def test_a_legacy_roster_is_judged_by_the_settings_of_its_own_run(zone, settings_latest, fetch):
    """Catches legacy captures all trusted or all refetched (R3.1)."""
    land_roster(zone, period=100, stamp="20260926T000000Z")
    land_settings(
        zone,
        stamp="20260926T000000Z",
        status={"latestScoringPeriod": settings_latest, "finalScoringPeriod": 180},
    )
    assert espn_rosters.needs_fetch(100, evidence=evidence_of(zone)) is fetch


@pytest.mark.parametrize(
    "settings",
    [
        None,
        {"finalScoringPeriod": 180},
        {"latestScoringPeriod": "300"},
        {"latestScoringPeriod": True},
    ],
    ids=["no settings capture", "no counter", "string counter", "boolean counter"],
)
def test_a_legacy_roster_without_usable_settings_is_fetched(zone, settings):
    """Catches finality assumed from absence (R3.2)."""
    land_roster(zone, period=100, stamp="20260926T000000Z")
    if settings is not None:
        land_settings(zone, stamp="20260926T000000Z", status=settings)
    land_settings(zone, stamp="20260927T000000Z", status={"latestScoringPeriod": 300})
    assert espn_rosters.needs_fetch(100, evidence=evidence_of(zone)) is True


def test_only_a_settings_payload_with_a_legacy_roster_stamp_is_read(zone, monkeypatch):
    """Catches every settings payload read on each run, or any roster payload read (R3.3)."""
    legacy = "20260926T000000Z"
    land_roster(zone, period=100, stamp=legacy)
    land_roster(zone, period=101, stamp="20260927T000000Z", source_status=status_of(300))
    wanted = land_settings(zone, stamp=legacy, status={"latestScoringPeriod": 300})
    land_settings(zone, stamp="20260927T000000Z", status={"latestScoringPeriod": 300})
    land_settings(zone, stamp=legacy, status={"latestScoringPeriod": 300}, league_id="99999")
    land_settings(zone, stamp=legacy, status={"latestScoringPeriod": 300}, season=2025)
    allowed = (wanted / "payload.json").resolve()
    reads = []

    def guard(real):
        def wrapped(self, *args, **kwargs):
            if self.name == "payload.json":
                if self.resolve() != allowed:
                    raise AssertionError(f"payload read: {self}")
                reads.append(self)
            return real(self, *args, **kwargs)

        return wrapped

    for name in ("read_bytes", "read_text", "open"):
        monkeypatch.setattr(Path, name, guard(getattr(Path, name)))
    evidence = evidence_of(zone)
    assert reads, "the legacy run's settings payload is the one that is read"
    assert {period: found.latest for period, found in evidence.items()} == {100: 300, 101: 300}


def test_a_newer_capture_with_a_null_status_leaves_a_settled_period_skipped(zone):
    """Catches a refresh un-settling a period: 'newest capture' for 'some capture' (R2.1)."""
    land_roster(zone, period=100, stamp="20270101T000001Z", source_status=status_of(108))
    land_roster(zone, period=100, stamp="20270101T000002Z", source_status=status_of(None))
    assert espn_rosters.needs_fetch(100, evidence=evidence_of(zone)) is False


def test_a_lagging_status_is_reported_and_the_next_run_clears_it(zone):
    """Catches a silent permanent refetch, and a period that never recovers (R4.1, R5.2)."""
    season = Season(zone)
    season.overrides[100] = 100
    summary, _ = season.run(101)
    assert summary.unproven == [100]
    season.overrides.clear()
    summary, requested = season.run(101)
    assert 100 in requested
    assert summary.unproven == []


def test_a_response_without_a_usable_status_is_unproven(zone):
    """Catches a period left closed-looking after a response that proves nothing."""
    season = Season(zone)
    season.overrides[2] = None
    summary, _ = season.run(4)
    assert summary.unproven == [2]


def test_a_finished_season_with_every_period_settled_fetches_and_reports_nothing(zone):
    """Catches periods that do not exist (181-187) asked for or reported as unproven (R4.1)."""
    for period in range(1, 181):
        land_roster(zone, period=period, source_status=status_of(188))
    summary, requested = Season(zone).run(188)
    assert requested == []
    assert (summary.skipped, summary.unproven) == (180, [])


# -- the fetch path: a counter that stops (ADR 0047) ---------------------------------------


def _run_at(zone, *, final, counter, at):
    """One backfill run stamped `at` after BASE whose responses all say `counter`."""
    requested = []

    def handler(request):
        requested.append(int(request.url.params["scoringPeriodId"]))
        status = {"finalScoringPeriod": final, "latestScoringPeriod": counter}
        return httpx.Response(200, json={"teams": [], "status": status})

    summary = espn_rosters.backfill_rosters(
        zone=zone,
        client=make_client(handler),
        season=SEASON,
        league_id=LEAGUE_ID,
        status={"latestScoringPeriod": counter, "finalScoringPeriod": final},
        fetched_at=_stamp(at),
    )
    return summary, requested


# Seasons of this league whose final period was MLB's last day: the counter rests at final + 1.
STOPPED_SHAPES = [(182, 183), (186, 187), (195, 196)]


@pytest.mark.parametrize(("final", "rest"), STOPPED_SHAPES, ids=["2022", "2020", "2024"])
def test_the_last_periods_settle_a_week_after_the_counter_stops_run_by_run(zone, final, rest):
    """Catches the defect: under ADR 0018 alone the last seven periods are fetched on every run.

    One run a day from the day after period `rest - 7`; the counter moves a day at a time
    until `rest`, first read on run `T` (day 0), and stays there. A period `p` from
    `rest - 8` is fetched through run `T + max(0, p + 8 - rest)` days and skipped after.
    """
    fetched_on = {}  # day relative to T -> periods requested
    for day in range(-6, 14):
        counter = min(rest + day, rest)
        _, requested = _run_at(zone, final=final, counter=counter, at=dt.timedelta(days=day))
        fetched_on[day] = set(requested)
    for period in range(rest - 8, final + 1):
        last_day = max(0, period + 8 - rest)
        fetched_days = [day for day in range(0, 14) if period in fetched_on[day]]
        assert fetched_days == list(range(0, last_day + 1)), period
    # the design's worked cases: the first of the last seven on T+1d, the final period on T+7d
    assert max(day for day in range(14) if rest - 7 in fetched_on[day]) == 1
    assert max(day for day in range(14) if final in fetched_on[day]) == 7
    # the final period: day -1 (counter 182 for the 2022 shape, still current) and T..T+7d
    assert [day for day in range(-6, 14) if final in fetched_on[day]] == [-1, *range(8)]


@pytest.mark.parametrize(("final", "rest"), STOPPED_SHAPES, ids=["2022", "2020", "2024"])
def test_a_finished_season_landed_in_one_run_settles_its_last_periods_within_a_week(
    zone, final, rest
):
    """Catches an off-by-one in the span or the comparison, and a past season settling too soon.

    Periods below `rest - 7` settle at once; period `p` of the last seven settles on the first
    run at least `p + 8 - rest` days after the landing.
    """
    summary, requested = _run_at(zone, final=final, counter=rest, at=dt.timedelta(0))
    assert requested == list(range(1, final + 1))
    assert summary.unproven == []
    last_seven = list(range(rest - 7, final + 1))
    _, requested = _run_at(zone, final=final, counter=rest, at=dt.timedelta(hours=6))
    assert requested == last_seven
    _, requested = _run_at(zone, final=final, counter=rest, at=dt.timedelta(days=6))
    assert requested == last_seven
    _, requested = _run_at(zone, final=final, counter=rest, at=dt.timedelta(days=7))
    assert requested == [final]
    _, requested = _run_at(zone, final=final, counter=rest, at=dt.timedelta(days=8))
    assert requested == []


def test_a_period_that_a_run_completes_the_week_of_is_proven_and_skipped_next_time(zone):
    """Catches in-run evidence not rebuilt: the period would be reported unproven (R1.7)."""
    land_roster(zone, period=100, source_status={"latest_scoring_period": None})
    summary, requested = _run_at(zone, final=100, counter=101, at=dt.timedelta(0))
    assert 100 in requested
    assert 100 not in summary.unproven
    for day in range(1, 7):
        _, requested = _run_at(zone, final=100, counter=101, at=dt.timedelta(days=day))
        assert 100 in requested
    summary, requested = _run_at(zone, final=100, counter=101, at=dt.timedelta(days=7))
    assert 100 in requested  # this capture completes the week: 101 seen on days 0 and 7
    assert 100 not in summary.unproven
    _, requested = _run_at(zone, final=100, counter=101, at=dt.timedelta(days=8))
    assert 100 not in requested


# -- the command ---------------------------------------------------------------------------


def _drive_backfill_espn(tmp_path, monkeypatch, *, settings_latest, roster_latest):
    monkeypatch.setenv("ESPN_S2", "s2-cookie-value")
    monkeypatch.setenv("SWID", "{swid-cookie-value}")
    monkeypatch.setenv("LEAGUE_ID", LEAGUE_ID)
    monkeypatch.setattr(cli, "load_env_file", lambda: None)
    serve_pro_schedule(monkeypatch)

    def handler(request):
        if request.url.params.get("scoringPeriodId") is None:
            return httpx.Response(
                200,
                json={
                    "status": {"latestScoringPeriod": settings_latest, "finalScoringPeriod": 180},
                    "topics": [],  # an empty page is a complete activity log
                },
            )
        status = {"latestScoringPeriod": roster_latest, "finalScoringPeriod": 180}
        return httpx.Response(200, json={"teams": [], "status": status})

    monkeypatch.setattr(cli, "espn_client", lambda _credentials: make_client(handler))
    return CliRunner().invoke(
        cli.app, ["backfill", "espn", "--season", str(SEASON), "--raw-root", str(tmp_path)]
    )


def test_backfill_espn_exits_non_zero_and_names_the_unproven_periods(tmp_path, monkeypatch):
    """Catches a period the league is past that no capture closed passing silently (R4.1)."""
    result = _drive_backfill_espn(tmp_path, monkeypatch, settings_latest=3, roster_latest=1)
    assert result.exit_code == 1
    assert "unproven scoring periods: [1, 2]" in result.output


def test_a_period_unsettled_by_a_later_fetch_of_the_same_run_is_fetched_on_the_next(zone):
    """Pins an accepted cost (ADR 0047; PR #121 review, F1): a period skipped as settled is not
    revisited when a later fetch of the same run shows the counter had not stopped.

    Period 1 reads counter 2 on days 0 and 7, so the calendar settles it. On day 8 the counter
    reads 10: the run skips period 1, then period 2's capture makes 2 a lagging status, which
    is never extended. Period 1 is fetched one run late, not never. Catches that delay growing
    past one run, and a change that revisits skipped periods going unnoticed in the ADR.
    """
    _run_at(zone, final=2, counter=2, at=dt.timedelta(0))
    _run_at(zone, final=2, counter=2, at=dt.timedelta(days=7))
    assert espn_rosters.needs_fetch(1, evidence=evidence_of(zone)) is False
    _, requested = _run_at(zone, final=2, counter=10, at=dt.timedelta(days=8))
    assert requested == [2]
    assert espn_rosters.needs_fetch(1, evidence=evidence_of(zone)) is True
    _, requested = _run_at(zone, final=2, counter=10, at=dt.timedelta(days=9))
    assert requested == [1]
    assert espn_rosters.needs_fetch(1, evidence=evidence_of(zone)) is False


def test_backfill_espn_exits_zero_when_only_closed_periods_are_in_the_window(tmp_path, monkeypatch):
    """Catches the re-check window treated as a failure (R6.2)."""
    result = _drive_backfill_espn(tmp_path, monkeypatch, settings_latest=3, roster_latest=3)
    assert result.exit_code == 0, result.output
    assert "unproven" not in result.output
