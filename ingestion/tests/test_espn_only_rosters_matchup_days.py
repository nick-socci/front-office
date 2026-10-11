"""Tests for `backfill espn --only rosters` and `--only matchup-days` (spec 0083, R1, R5.1).

No test here touches the network or reads a real .env: every client has a fake transport.
"""

import httpx
import pytest
from typer.testing import CliRunner

from front_office import cli
from front_office.landing import LandingZone

SEASON = 2026
LEAGUE_ID = "73677"
FINAL = 3  # a small fake season
LATEST = 20  # well past FINAL + 7, so every period is closed and settled on first capture
COOKIE_VALUES = ("s2-cookie-value", "swid-cookie-value")


def make_client(handler, *, cookies=None):
    from front_office.http_client import HttpClient, SourceLimits

    return HttpClient(
        source="espn",
        limits=SourceLimits(min_interval_s=0.0, max_attempts=2, backoff_base_s=0.0),
        transport=httpx.MockTransport(handler),
        cookies=cookies,
        sleep=lambda _seconds: None,
    )


def set_credentials(monkeypatch):
    monkeypatch.setenv("ESPN_S2", COOKIE_VALUES[0])
    monkeypatch.setenv("SWID", "{" + COOKIE_VALUES[1] + "}")
    monkeypatch.setenv("LEAGUE_ID", LEAGUE_ID)
    monkeypatch.setattr(cli, "load_env_file", lambda: None)


def views(request):
    return request.url.params.get_list("view")


def period_of(request):
    return request.url.params.get("scoringPeriodId")


def is_pro_schedule(request):
    return "/leagues/" not in request.url.path


def is_transactions(request):
    return "/communication/" in request.url.path or "kona_league_communication" in views(request)


def is_matchups(request):
    return "mMatchupScore" in views(request) or "mScoreboard" in views(request)


def status(first=1, final=FINAL):
    return {"firstScoringPeriod": first, "latestScoringPeriod": LATEST, "finalScoringPeriod": final}


def league_handler(request):
    if is_matchups(request):
        return httpx.Response(200, json={"teams": [], "schedule": [], "status": status()})
    if period_of(request) is None:
        return httpx.Response(200, json={"status": status(), "topics": []})
    return httpx.Response(200, json={"teams": [], "status": status()})


def run(tmp_path, monkeypatch, *args, handler=league_handler):
    """Run `backfill espn` with fake public and league clients; return the result and requests."""
    set_credentials(monkeypatch)
    seen = []

    def public(request):
        seen.append(request)
        return httpx.Response(200, json={"settings": {"proTeams": []}})

    def league(request):
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(cli, "espn_public_client", lambda: make_client(public))
    monkeypatch.setattr(
        cli, "espn_client", lambda credentials: make_client(league, cookies=credentials.cookies())
    )
    result = CliRunner().invoke(
        cli.app,
        ["backfill", "espn", "--season", str(SEASON), "--raw-root", str(tmp_path), *args],
    )
    return result, seen


def land_settings(tmp_path, *, stamp="20260101T000000Z", season=SEASON, league_id=LEAGUE_ID, **kw):
    """Commit a settings capture the way `espn/settings.py` does."""
    LandingZone(root=tmp_path).write(
        source="espn",
        endpoint="settings",
        partitions={"season": season, "league_id": league_id},
        name=f"fetched_at={stamp}",
        payload={"status": status(**kw)},
        request={"url": "https://example.test", "params": {"view": "mSettings,mStatus"}},
        fetched_at=stamp,
    )


def only_rosters(tmp_path, monkeypatch):
    return run(tmp_path, monkeypatch, "--only", "rosters")


def only_matchup_days(tmp_path, monkeypatch, *args, handler=league_handler):
    return run(tmp_path, monkeypatch, "--only", "matchup-days", *args, handler=handler)


def endpoint_of(capture, root):
    return capture.path.relative_to(root).parts[1]


# --- --only rosters (R1.1) -------------------------------------------------------------


def test_only_rosters_requests_settings_teams_then_each_roster_and_nothing_else(
    tmp_path, monkeypatch
):
    """Catches a wrong order, a missing cookie, or a transaction, matchups or schedule request."""
    result, seen = only_rosters(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert len(seen) == 2 + FINAL
    settings, teams, *rosters = seen
    assert views(settings) == ["mSettings", "mStatus"] and period_of(settings) is None
    assert views(teams) == ["mTeam"] and period_of(teams) is None
    assert [period_of(r) for r in rosters] == [str(p) for p in range(1, FINAL + 1)]
    assert all(views(r) == ["mRoster"] for r in rosters)
    for request in seen:
        assert "espn_s2=s2-cookie-value" in request.headers["cookie"]
        assert not is_pro_schedule(request), "no pro-schedule request"
        assert not is_transactions(request), "no transaction request"
        assert not is_matchups(request), "no matchups request"


def test_only_rosters_lands_settings_teams_and_roster_under_one_stamp(tmp_path, monkeypatch):
    """Catches a stray matchups/transactions/pro_schedule capture or a second fetched_at."""
    result, _ = only_rosters(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    captures = list(LandingZone(root=tmp_path).iter_landed(source="espn"))
    endpoints = sorted({endpoint_of(c, tmp_path) for c in captures})
    assert endpoints == ["roster", "settings", "teams"]
    assert len(captures) == 2 + FINAL
    assert len({c.meta["fetched_at"] for c in captures}) == 1


# --- --only matchup-days (R1.2-R1.4, R1.6, R1.7) ----------------------------------------


def test_only_matchup_days_requests_each_period_in_order_and_nothing_else(tmp_path, monkeypatch):
    """Catches a wrong view set, a wrong period range or order, or a stray league request."""
    land_settings(tmp_path)
    result, seen = only_matchup_days(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert [period_of(r) for r in seen] == [str(p) for p in range(1, FINAL + 1)]
    for request in seen:
        assert f"/leagues/{LEAGUE_ID}" in request.url.path
        assert sorted(views(request)) == ["mMatchupScore", "mScoreboard"]
        assert "espn_s2=s2-cookie-value" in request.headers["cookie"]
        assert not is_transactions(request)


def test_only_matchup_days_starts_at_the_first_scoring_period_of_the_settings(
    tmp_path, monkeypatch
):
    """Catches a range that assumes the season starts at period 1 (R1.2)."""
    land_settings(tmp_path, first=2, final=4)
    result, seen = only_matchup_days(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert [period_of(r) for r in seen] == ["2", "3", "4"]


def test_only_matchup_days_reads_the_newest_settings_capture(tmp_path, monkeypatch):
    """Catches the range being taken from an older settings capture (R1.2)."""
    land_settings(tmp_path, stamp="20250101T000000Z", final=5)
    land_settings(tmp_path, stamp="20260101T000000Z", final=2)
    _, seen = only_matchup_days(tmp_path, monkeypatch)
    assert [period_of(r) for r in seen] == ["1", "2"]


def test_only_matchup_days_lands_each_period_under_its_endpoint_and_partitions(
    tmp_path, monkeypatch
):
    """Catches a wrong endpoint, a missing scoring_period partition or request param (R1.2)."""
    land_settings(tmp_path)
    result, _ = only_matchup_days(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    zone = LandingZone(root=tmp_path)
    landed = list(zone.iter_landed(source="espn", endpoint="matchup_days"))
    assert len(landed) == FINAL
    assert sorted(c.meta["partitions"]["scoring_period"] for c in landed) == list(
        range(1, FINAL + 1)
    )
    for capture in landed:
        partitions = capture.meta["partitions"]
        assert set(partitions) == {"season", "league_id", "scoring_period"}
        assert partitions["season"] == SEASON and str(partitions["league_id"]) == LEAGUE_ID
        assert capture.meta["params"]["scoringPeriodId"] == partitions["scoring_period"]
    others = {endpoint_of(c, tmp_path) for c in zone.iter_landed(source="espn")} - {
        "matchup_days",
        "settings",
    }
    assert others == set(), "nothing but matchup_days beside the committed settings"


def test_only_matchup_days_keeps_credentials_out_of_the_zone_and_the_output(tmp_path, monkeypatch):
    """Catches a cookie value reaching a payload, sidecar, or log line (R1.7)."""
    land_settings(tmp_path)
    result, _ = only_matchup_days(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert files
    for path in files:
        text = path.read_text(errors="replace")
        for value in COOKIE_VALUES:
            assert value not in text, f"{value} in {path}"
    for value in COOKIE_VALUES:
        assert value not in result.output


def test_only_matchup_days_skips_landed_periods_and_refresh_requests_them_again(
    tmp_path, monkeypatch
):
    """Catches a second run re-requesting landed periods, or --refresh skipping them (R1.3)."""
    land_settings(tmp_path)
    first, _ = only_matchup_days(tmp_path, monkeypatch)
    assert first.exit_code == 0, first.output

    second, seen = only_matchup_days(tmp_path, monkeypatch)
    assert second.exit_code == 0, second.output
    assert seen == []

    refreshed, seen = only_matchup_days(tmp_path, monkeypatch, "--refresh")
    assert refreshed.exit_code == 0, refreshed.output
    assert [period_of(r) for r in seen] == [str(p) for p in range(1, FINAL + 1)]
    zone = LandingZone(root=tmp_path)
    assert len(list(zone.iter_landed(source="espn", endpoint="matchup_days"))) == 2 * FINAL


def test_only_matchup_days_tries_every_period_when_one_fails_and_names_it(tmp_path, monkeypatch):
    """Catches a failed period stopping the run, exiting 0, or going unnamed (R1.3)."""
    land_settings(tmp_path)

    def period_two_is_gone(request):
        if period_of(request) == "2":
            return httpx.Response(404, json={})
        return league_handler(request)

    result, seen = only_matchup_days(tmp_path, monkeypatch, handler=period_two_is_gone)
    assert result.exit_code != 0
    assert "Traceback" not in result.output
    assert {period_of(r) for r in seen} == {"1", "2", "3"}, "every period is tried"
    zone = LandingZone(root=tmp_path)
    landed = zone.iter_landed(source="espn", endpoint="matchup_days")
    assert sorted(c.meta["partitions"]["scoring_period"] for c in landed) == [1, 3]
    assert "[2]" in result.output, "the failed period is named"


@pytest.mark.parametrize(
    "settings_of",
    [None, {"season": SEASON - 1}, {"league_id": "99999"}],
    ids=["none", "other_season", "other_league"],
)
def test_only_matchup_days_without_settings_makes_no_request_and_says_so(
    tmp_path, monkeypatch, settings_of
):
    """Catches a request made on guessed periods, or a silent exit 0 (R1.4)."""
    if settings_of is not None:
        land_settings(tmp_path, **settings_of)
    result, seen = only_matchup_days(tmp_path, monkeypatch)
    assert result.exit_code != 0
    assert seen == []
    assert "settings" in result.output.lower()
    assert "Traceback" not in result.output
    zone = LandingZone(root=tmp_path)
    assert list(zone.iter_landed(source="espn", endpoint="matchup_days")) == []


# --- both (R1.5) ------------------------------------------------------------------------


def test_an_unknown_only_value_is_still_refused(tmp_path, monkeypatch):
    """Catches the new values loosening the check to accept anything (R1.5)."""
    land_settings(tmp_path)
    result, seen = run(tmp_path, monkeypatch, "--only", "bogus")
    assert result.exit_code != 0
    assert seen == []
    assert list(LandingZone(root=tmp_path).iter_landed(source="espn", endpoint="roster")) == []
