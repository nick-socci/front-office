"""Tests for `backfill espn --only matchups` (spec 0085, R1.1-R1.5 and R4.1).

No test here touches the network or reads a real .env: every client has a fake transport.
"""

import re

import httpx
import pytest
from typer.testing import CliRunner

from front_office import cli
from front_office.landing import LandingZone

SEASON = 2026
STATUS = {"latestScoringPeriod": 7, "finalScoringPeriod": 180}
SCHEDULE = {"settings": {"proTeams": [{"id": 1, "proGamesByScoringPeriod": {}}]}}


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
    monkeypatch.setenv("ESPN_S2", "s2-cookie-value")
    monkeypatch.setenv("SWID", "{swid-cookie-value}")
    monkeypatch.setenv("LEAGUE_ID", "73677")
    monkeypatch.setattr(cli, "load_env_file", lambda: None)


def is_pro_schedule(request):
    return request.url.path.endswith(f"/seasons/{SEASON}")


def views(request):
    return request.url.params.get_list("view")


def league_handler(request):
    if request.url.params.get("scoringPeriodId") is None:
        return httpx.Response(200, json={"status": STATUS, "topics": []})
    return httpx.Response(200, json={"teams": [], "status": STATUS})


def ok(request):
    return httpx.Response(200, json=SCHEDULE)


def malformed(request):
    return httpx.Response(200, json={"messages": ["no such view"]})


def exhausted(request):
    return httpx.Response(503, json={})


def login_required(request):
    return httpx.Response(401, json={})


def withdrawn(request):
    return httpx.Response(404, json={})


def run(tmp_path, monkeypatch, pro_handler=ok, *args):
    """Run `backfill espn` with fake public and league clients; return the result and requests."""
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
        cli, "espn_client", lambda credentials: make_client(league, cookies=credentials.cookies())
    )
    result = CliRunner().invoke(
        cli.app,
        ["backfill", "espn", "--season", str(SEASON), "--raw-root", str(tmp_path), *args],
    )
    return result, seen


def only_matchups(tmp_path, monkeypatch, pro_handler=ok):
    return run(tmp_path, monkeypatch, pro_handler, "--only", "matchups")


def test_only_matchups_requests_schedule_then_settings_then_matchups_and_nothing_else(
    tmp_path, monkeypatch
):
    """Catches a wrong order, a cookie on the public request, or an extra league request."""
    result, seen = only_matchups(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    assert len(seen) == 3
    schedule, settings, matchups = seen
    assert is_pro_schedule(schedule) and "cookie" not in schedule.headers
    assert views(settings) == ["mSettings", "mStatus"]
    assert views(matchups) == ["mMatchupScore", "mScoreboard"]
    for request in (settings, matchups):
        assert "espn_s2=s2-cookie-value" in request.headers["cookie"]
    for request in seen:
        assert request.url.params.get("scoringPeriodId") is None, "no roster request"
        assert "mTeam" not in views(request), "no teams request"
        assert "kona_league_communication" not in views(request), "no transactions request"


def test_only_matchups_lands_three_captures_under_one_stamp(tmp_path, monkeypatch):
    """Catches a stray teams/transactions/roster capture or a second fetched_at."""
    result, _ = only_matchups(tmp_path, monkeypatch)
    assert result.exit_code == 0, result.output
    zone = LandingZone(root=tmp_path)
    captures = list(zone.iter_landed(source="espn"))
    endpoints = sorted(c.path.relative_to(tmp_path).parts[1] for c in captures)
    assert endpoints == ["matchups", "pro_schedule", "settings"]
    assert len({c.meta["fetched_at"] for c in captures}) == 1


def test_only_matchups_prints_the_lines_a_full_run_prints(tmp_path, monkeypatch):
    """Catches a missing landed line or scoring-periods status line."""
    result, _ = only_matchups(tmp_path, monkeypatch)
    for line in ("landed pro schedule -> ", "landed settings -> ", "landed matchups -> "):
        assert line in result.output
    assert "scoring periods: latest=7 final=180" in result.output
    assert "teams" not in result.output and "rosters" not in result.output


def test_only_matchups_lands_what_a_full_run_lands(tmp_path, monkeypatch):
    """Catches settings or matchups landed with other endpoints, partitions or params (R1.2)."""
    only_dir, full_dir = tmp_path / "only", tmp_path / "full"
    only_matchups(only_dir, monkeypatch)
    run(full_dir, monkeypatch)
    for endpoint in ("settings", "matchups", "pro_schedule"):
        (a,) = LandingZone(root=only_dir).iter_landed(source="espn", endpoint=endpoint)
        (b,) = LandingZone(root=full_dir).iter_landed(source="espn", endpoint=endpoint)
        assert a.meta["partitions"] == b.meta["partitions"], endpoint
        assert a.meta["params"] == b.meta["params"], endpoint
        assert a.path.relative_to(only_dir).parts[:-2] == b.path.relative_to(full_dir).parts[:-2]


@pytest.mark.parametrize(
    "pro_handler",
    [malformed, exhausted, login_required, withdrawn],
    ids=["malformed", "exhausted", "login_required", "withdrawn"],
)
def test_only_matchups_pro_schedule_failure_still_lands_the_league_and_exits_1(
    tmp_path, monkeypatch, pro_handler
):
    """Catches a failed schedule stopping settings and matchups, or exiting 0 (R1.3)."""
    result, _ = only_matchups(tmp_path, monkeypatch, pro_handler)
    assert result.exit_code == 1
    assert "pro schedule: " in result.stderr
    assert "Traceback" not in result.output
    zone = LandingZone(root=tmp_path)
    assert list(zone.iter_landed(source="espn", endpoint="pro_schedule")) == []
    for endpoint in ("settings", "matchups"):
        assert list(zone.iter_landed(source="espn", endpoint=endpoint)), endpoint
    for endpoint in ("teams", "transactions", "roster"):
        assert list(zone.iter_landed(source="espn", endpoint=endpoint)) == [], endpoint


def test_an_unknown_only_value_is_refused_naming_both_accepted_values(tmp_path, monkeypatch):
    """Catches an unknown --only landing anything, or a message hiding the new value."""
    result, seen = run(tmp_path, monkeypatch, ok, "--only", "settings")
    assert result.exit_code != 0
    assert seen == []
    assert "pro-schedule" in result.output and "matchups" in result.output
    assert list(LandingZone(root=tmp_path).iter_landed(source="espn")) == []


def test_audit_help_says_it_judges_a_season_landed_whole():
    """Catches the audit help omitting the --only matchups caveat (R1.5)."""
    # A wide terminal so the sentence is not wrapped, and the styling stripped: where
    # colour is forced, as in CI, an option name in the help is wrapped in escape codes
    # and its words are no longer adjacent.
    result = CliRunner().invoke(cli.app, ["audit", "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    text = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
    assert "--only matchups" in text
    assert "rosters" in text and "boxscores" in text
