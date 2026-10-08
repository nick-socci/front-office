"""Tests for the ESPN pro schedule capture (spec 0073, R1.x and R7.1).

No test here touches the network or reads a real .env: every client has a fake transport.
The pro schedule is a public, league-free resource, so the tests that matter most assert
what is *absent* from it: cookies, a league id, and any dependence on credentials.
"""

import json

import httpx
import pytest
from typer.testing import CliRunner

from front_office import cli
from front_office.espn import pro_schedule
from front_office.espn.client import espn_public_client, game_url
from front_office.http_client import HttpClient, SourceLimits
from front_office.landing import LandingZone

SEASON = 2026
LEAGUE_ID = "73677"
SCHEDULE = {
    "settings": {
        "proTeams": [
            {"id": 1, "proGamesByScoringPeriod": {"1": [{"id": 401, "date": 1774900000000}]}}
        ]
    }
}


@pytest.fixture
def zone(tmp_path):
    return LandingZone(root=tmp_path)


def make_client(handler, *, cookies=None):
    return HttpClient(
        source="espn",
        limits=SourceLimits(min_interval_s=0.0, max_attempts=2, backoff_base_s=0.0),
        transport=httpx.MockTransport(handler),
        cookies=cookies,
        sleep=lambda _seconds: None,
    )


def land(zone, handler=None, *, stamp="20261007T000000Z", seen=None):
    def serve(request):
        if seen is not None:
            seen.append(request)
        return (handler or (lambda r: httpx.Response(200, json=SCHEDULE)))(request)

    return pro_schedule.backfill_pro_schedule(
        zone=zone, client=make_client(serve), season=SEASON, fetched_at=stamp
    )


def test_game_url_is_the_season_resource_without_a_league():
    """Catches a league segment creeping into a public URL."""
    assert game_url(2026).endswith("/apis/v3/games/flb/seasons/2026")
    assert "leagues" not in game_url(2026)


def test_the_public_client_carries_no_cookies_and_reads_no_environment(monkeypatch):
    """Catches credentials sent to, or required by, a public request (R1.2)."""
    for name in ("ESPN_S2", "SWID", "LEAGUE_ID"):
        monkeypatch.delenv(name, raising=False)
    client = espn_public_client()
    try:
        assert client.source == "espn"
        assert len(client._client.cookies.jar) == 0
    finally:
        client.close()


def test_the_request_is_the_game_resource_with_the_schedule_view(zone):
    """Catches a wrong URL or view (R1.1)."""
    seen = []
    land(zone, seen=seen)
    assert len(seen) == 1
    url = seen[0].url
    assert url.path.endswith("/apis/v3/games/flb/seasons/2026")
    assert dict(url.params) == {"view": "proTeamSchedules_wl"}


def test_no_cookie_header_is_sent(zone):
    """Catches a login cookie attached to the public request (R1.2)."""
    seen = []
    land(zone, seen=seen)
    assert "cookie" not in seen[0].headers


def test_the_capture_is_a_season_level_espn_capture_with_the_payload_unchanged(zone):
    """Catches a league partition, a rewritten payload, or a wrong sidecar (R1.1, R1.5)."""
    path = land(zone, stamp="20261007T000000Z")
    assert path == zone.root / "espn/pro_schedule/season=2026/fetched_at=20261007T000000Z"
    (capture,) = zone.iter_landed(source="espn", endpoint="pro_schedule")
    assert capture.meta["partitions"] == {"season": 2026}
    assert capture.meta["params"] == {"view": "proTeamSchedules_wl"}
    assert capture.meta["url"].startswith(game_url(2026))
    assert capture.meta["fetched_at"] == "20261007T000000Z"
    assert json.loads((path / "payload.json").read_text()) == SCHEDULE


def test_each_run_lands_a_new_capture(zone):
    """Catches a snapshot endpoint treated as land-once (R1.5)."""
    first = land(zone, stamp="20261007T000000Z")
    second = land(zone, stamp="20261008T000000Z")
    assert first != second
    assert len(list(zone.iter_landed(source="espn", endpoint="pro_schedule"))) == 2


@pytest.mark.parametrize(
    "body",
    [
        {"messages": ["The view proTeamSchedules_wl is not supported"]},
        [{"settings": {"proTeams": []}}],
        {"settings": {}},
        {"settings": {"proTeams": {"1": {}}}},
        {"settings": [], "proTeams": []},
    ],
    ids=["error-object", "list", "no-proTeams", "proTeams-not-a-list", "settings-not-object"],
)
def test_a_malformed_response_lands_nothing_and_raises(zone, body):
    """Catches an error page landed as a schedule (R1.6)."""
    with pytest.raises(pro_schedule.ProScheduleMalformed) as error:
        land(zone, lambda request: httpx.Response(200, json=body))
    assert "is not supported" not in str(error.value), "the payload is not dumped"
    assert list(zone.iter_landed(source="espn", endpoint="pro_schedule")) == []


# -- the command ---------------------------------------------------------------------------


def set_credentials(monkeypatch):
    monkeypatch.setenv("ESPN_S2", "s2-cookie-value")
    monkeypatch.setenv("SWID", "{swid-cookie-value}")
    monkeypatch.setenv("LEAGUE_ID", LEAGUE_ID)
    monkeypatch.setattr(cli, "load_env_file", lambda: None)


def is_pro_schedule(request):
    return request.url.path.endswith(f"/seasons/{SEASON}")


def league_handler(request):
    if request.url.params.get("scoringPeriodId") is None:
        return httpx.Response(
            200,
            json={
                "status": {"latestScoringPeriod": 1, "finalScoringPeriod": 180},
                "topics": [],
            },
        )
    return httpx.Response(
        200, json={"teams": [], "status": {"latestScoringPeriod": 1, "finalScoringPeriod": 180}}
    )


def full_run(tmp_path, monkeypatch, pro_handler):
    """Run `backfill espn` with a cookie-carrying league client and a public client."""
    set_credentials(monkeypatch)
    seen = []

    def public(request):
        seen.append(request)
        return pro_handler(request)

    def league(request):
        seen.append(request)
        return league_handler(request)

    monkeypatch.setattr(cli, "espn_public_client", lambda: make_client(public))
    monkeypatch.setattr(
        cli,
        "espn_client",
        lambda credentials: make_client(league, cookies=credentials.cookies()),
    )
    result = CliRunner().invoke(
        cli.app, ["backfill", "espn", "--season", str(SEASON), "--raw-root", str(tmp_path)]
    )
    return result, seen


def ok(request):
    return httpx.Response(200, json=SCHEDULE)


def stamps(zone, endpoint):
    return {c.meta["fetched_at"] for c in zone.iter_landed(source="espn", endpoint=endpoint)}


def test_a_full_run_lands_the_schedule_first_under_the_runs_stamp_without_cookies(
    tmp_path, monkeypatch
):
    """Catches the schedule landed late, under another stamp, or with the login (R1.2, R1.3)."""
    result, seen = full_run(tmp_path, monkeypatch, ok)
    assert result.exit_code == 0, result.output
    assert is_pro_schedule(seen[0]), "the pro schedule is the first request"
    assert "cookie" not in seen[0].headers
    league = [r for r in seen if not is_pro_schedule(r)]
    assert league and all("espn_s2=s2-cookie-value" in r.headers["cookie"] for r in league)
    zone = LandingZone(root=tmp_path)
    run_stamps = stamps(zone, "pro_schedule") | stamps(zone, "settings")
    assert len(stamps(zone, "pro_schedule")) == 1
    assert len(run_stamps) == 1, "one fetched_at for the whole run"
    assert result.output.index("landed pro schedule") < result.output.index("landed settings")


def malformed(request):
    return httpx.Response(200, json={"messages": ["no such view"]})


def exhausted(request):
    return httpx.Response(503, json={})


def login_required(request):
    # ESPN putting the view behind a login: the one failure the league requests would not share.
    return httpx.Response(401, json={})


def withdrawn(request):
    return httpx.Response(404, json={})


@pytest.mark.parametrize(
    "pro_handler",
    [malformed, exhausted, login_required, withdrawn],
    ids=["malformed", "exhausted", "login_required", "withdrawn"],
)
def test_a_failing_pro_schedule_does_not_stop_the_league_run_but_exits_1(
    tmp_path, monkeypatch, pro_handler
):
    """Catches one public request stopping the league's data, or a failure exiting 0 (R1.7)."""
    result, _ = full_run(tmp_path, monkeypatch, pro_handler)
    assert result.exit_code == 1
    assert "pro schedule: " in result.stderr
    assert "cookies" not in result.stderr.lower(), "no login was sent, so none expired"
    assert "Traceback" not in result.output
    zone = LandingZone(root=tmp_path)
    assert list(zone.iter_landed(source="espn", endpoint="pro_schedule")) == []
    for endpoint in ("settings", "teams", "matchups", "transactions", "roster"):
        assert list(zone.iter_landed(source="espn", endpoint=endpoint)), endpoint


def forbid(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("credentials must not be touched")

    monkeypatch.setattr(cli, "load_env_file", boom)
    monkeypatch.setattr(cli.EspnCredentials, "from_env", boom)
    monkeypatch.setattr(cli, "espn_client", boom)


def test_only_pro_schedule_needs_no_credentials(tmp_path, monkeypatch):
    """Catches credentials or .env required for a public request (R1.4)."""
    for name in ("ESPN_S2", "SWID", "LEAGUE_ID"):
        monkeypatch.delenv(name, raising=False)
    forbid(monkeypatch)
    seen = []

    def serve(request):
        seen.append(request)
        return httpx.Response(200, json=SCHEDULE)

    monkeypatch.setattr(cli, "espn_public_client", lambda: make_client(serve))
    result = CliRunner().invoke(
        cli.app,
        [
            "backfill",
            "espn",
            "--season",
            str(SEASON),
            "--only",
            "pro-schedule",
            "--raw-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "landed pro schedule -> " in result.output
    assert len(seen) == 1 and "cookie" not in seen[0].headers
    zone = LandingZone(root=tmp_path)
    assert len(list(zone.iter_landed(source="espn", endpoint="pro_schedule"))) == 1
    assert list(zone.iter_landed(source="espn", endpoint="settings")) == []


@pytest.mark.parametrize(
    "pro_handler",
    [malformed, exhausted, login_required, withdrawn],
    ids=["malformed", "exhausted", "login_required", "withdrawn"],
)
def test_only_pro_schedule_failure_exits_non_zero(tmp_path, monkeypatch, pro_handler):
    """Catches a failed stand-alone fetch exiting 0 (R1.7)."""
    forbid(monkeypatch)
    monkeypatch.setattr(cli, "espn_public_client", lambda: make_client(pro_handler))
    result = CliRunner().invoke(
        cli.app,
        [
            "backfill",
            "espn",
            "--season",
            "2026",
            "--only",
            "pro-schedule",
            "--raw-root",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "pro schedule: " in result.stderr
    assert "Traceback" not in result.output
    assert list(LandingZone(root=tmp_path).iter_landed(source="espn")) == []


def test_an_unknown_only_value_is_rejected(tmp_path, monkeypatch):
    """Catches a typo in --only silently running the full league backfill."""
    forbid(monkeypatch)
    result = CliRunner().invoke(
        cli.app,
        ["backfill", "espn", "--season", "2026", "--only", "settings", "--raw-root", str(tmp_path)],
    )
    assert result.exit_code != 0
    assert list(LandingZone(root=tmp_path).iter_landed(source="espn")) == []
