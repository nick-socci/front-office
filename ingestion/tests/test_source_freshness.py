"""The source-freshness declarations are held by tests (spec 0114, ADR 0050).

Freshness itself cannot be a gate: the fixtures' newest capture is months old by design.
What can be held in CI is the declarations: `raw_feeds` declares `raw.api_responses` once
per feed, each with a filter that selects the feed's run marker.

The checks are small pure functions that take parsed data and return a list of problems.
Each is run twice: against the committed files (no problems expected) and against a
deliberately wrong copy built in the test (the problem expected), so each check is shown
to fail, and keeps being shown to.
"""

import copy
import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml

from front_office.landing import LandingZone

REPO = Path(__file__).resolve().parents[2]
STAGING = REPO / "dbt/models/staging"
FIXTURES = REPO / "fixtures/landing"

LOADED_AT = "strptime(fetched_at, '%Y%m%dT%H%M%SZ')"
SEASON_PATH = "json_extract_string(partitions, '$.season')"
# The feeds whose captures carry a season, and whose marker counts only in the latest one.
SEASON_SCOPED = {"mlb", "espn"}
# R1.1: feed -> (declaration name, its run marker's endpoint).
MARKERS = {
    "mlb": ("mlb_runs", "schedule"),
    "espn": ("espn_runs", "settings"),
    "idmap": ("idmap_runs", "player_id_map"),
}
THRESHOLDS = {
    "mlb_runs": {
        "warn_after": {"count": 36, "period": "hour"},
        "error_after": {"count": 7, "period": "day"},
    },
    "espn_runs": {
        "warn_after": {"count": 36, "period": "hour"},
        "error_after": {"count": 7, "period": "day"},
    },
    "idmap_runs": {"warn_after": {"count": 14, "period": "day"}},
}


class FixtureCapture(NamedTuple):
    feed: str
    endpoint: str
    partitions: dict
    path: str


# -- reading the committed files ----------------------------------------------------------


def find_source(name):
    """The named source from any YAML under dbt/models/staging, or None."""
    for path in sorted(STAGING.rglob("*.yml")):
        for source in (yaml.safe_load(path.read_text()) or {}).get("sources") or []:
            if source.get("name") == name:
                return source
    return None


def load_raw_feeds():
    source = find_source("raw_feeds")
    if source is None:
        pytest.fail("no source named raw_feeds under dbt/models/staging (task 3 creates it)")
    return source


def load_raw():
    source = find_source("raw")
    if source is None:
        pytest.fail("no source named raw under dbt/models/staging")
    return source


def fixture_captures():
    zone = LandingZone(FIXTURES)
    return [
        FixtureCapture(
            capture.meta["source"],
            capture.meta["endpoint"],
            capture.meta["partitions"],
            str(capture.directory.relative_to(REPO)),
        )
        for capture in zone.committed()
    ]


# -- parsing a declaration ----------------------------------------------------------------


def collapse(text):
    return " ".join(str(text).split())


def table_filter(table):
    return (table.get("freshness") or {}).get("filter")


def parse_filter(text):
    """(feed, endpoint) from the filter's opening clauses, or None when it has none."""
    found = re.match(r"source = '([^']+)' and endpoint = '([^']+)'", collapse(text or ""))
    return (found.group(1), found.group(2)) if found else None


def expected_filter(feed, endpoint):
    text = f"source = '{feed}' and endpoint = '{endpoint}'"
    if feed in SEASON_SCOPED:
        text += (
            f" and {SEASON_PATH} = ( select max({SEASON_PATH}) from raw.api_responses"
            f" where source = '{feed}' and endpoint = '{endpoint}' )"
        )
    return text


def declared(source):
    """(table name, feed, endpoint) for every table whose filter names a feed and endpoint."""
    found = []
    for table in source.get("tables") or []:
        parsed = parse_filter(table_filter(table))
        if parsed:
            found.append((table.get("name"), *parsed))
    return found


# -- the checks: parsed data in, a list of problems out -----------------------------------


def feed_problems(source, captures):
    """R3.1: the feeds filtered for are the feeds with fixtures, both directions."""
    filtered = {feed for _name, feed, _endpoint in declared(source)}
    fixtured = {capture.feed for capture in captures}
    problems = [
        f"feed {feed} has fixtures and no declaration" for feed in sorted(fixtured - filtered)
    ]
    problems += [
        f"feed {feed} is declared but has no fixtures" for feed in sorted(filtered - fixtured)
    ]
    return problems


def endpoint_problems(source, captures):
    """R3.2: each declaration's endpoint is one its feed has a capture of."""
    held = {(capture.feed, capture.endpoint) for capture in captures}
    return [
        f"{name}: endpoint {endpoint} has no fixture capture in feed {feed}"
        for name, feed, endpoint in declared(source)
        if (feed, endpoint) not in held
    ]


def filter_problems(source):
    """R3.3: each filter is exactly the text built from its one feed and endpoint."""
    problems = []
    for table in source.get("tables") or []:
        name = table.get("name")
        text = table_filter(table)
        if not text:
            problems.append(f"{name}: has no freshness filter")
            continue
        parsed = parse_filter(text)
        if parsed is None:
            problems.append(f"{name}: filter names no feed and endpoint: {collapse(text)}")
        elif collapse(text) != expected_filter(*parsed):
            problems.append(
                f"{name}: filter is not the text built from {parsed[0]}/{parsed[1]}: "
                f"{collapse(text)} (expected {expected_filter(*parsed)})"
            )
    twice = Counter(feed for _name, feed, _endpoint in declared(source))
    problems += [f"feed {feed} is declared {n} times" for feed, n in sorted(twice.items()) if n > 1]
    return problems


def config_problems(source):
    """R3.4: schema, identifier and the exact loaded_at_field."""
    problems = []
    if source.get("schema") != "raw":
        problems.append(f"source schema is {source.get('schema')!r}, not 'raw'")
    for table in source.get("tables") or []:
        name = table.get("name")
        if table.get("identifier") != "api_responses":
            problems.append(f"{name}: identifier is {table.get('identifier')!r}")
        if table.get("loaded_at_field") != LOADED_AT:
            problems.append(f"{name}: loaded_at_field is {table.get('loaded_at_field')!r}")
    return problems


def season_problems(source, captures):
    """R3.5: each capture of a season-scoped marker has a four-digit-year season."""
    scoped = {
        (feed, endpoint)
        for table in source.get("tables") or []
        if SEASON_PATH in collapse(table_filter(table) or "")
        for feed, endpoint in [parse_filter(table_filter(table)) or (None, None)]
    }
    problems = []
    for capture in captures:
        if (capture.feed, capture.endpoint) not in scoped:
            continue
        season = capture.partitions.get("season")
        if not re.fullmatch(r"\d{4}", str(season)):
            problems.append(
                f"{capture.feed}/{capture.endpoint} capture {capture.path} has season "
                f"{season!r} in partitions {capture.partitions}"
            )
    return problems


def marker_problems(source):
    """R1.1: the markers are the designed ones, under the designed table names."""
    found = {feed: (name, endpoint) for name, feed, endpoint in declared(source)}
    return [
        f"feed {feed}: marker is {found.get(feed)}, expected {expected}"
        for feed, expected in MARKERS.items()
        if found.get(feed) != expected
    ] + [f"unexpected feed {feed} declared" for feed in sorted(set(found) - set(MARKERS))]


def raw_table_problems(source):
    """R1.3: raw.api_responses carries no freshness and no loaded_at_field."""
    tables = [t for t in source.get("tables") or [] if t.get("name") == "api_responses"]
    if not tables:
        return ["raw.api_responses is not declared"]
    return [
        f"api_responses still has {key}"
        for key in ("freshness", "loaded_at_field")
        if key in tables[0]
    ]


def threshold_problems(source):
    """R2.1, R2.2: the thresholds are the ones in the design, and idmap has no error."""
    problems = []
    tables = {t.get("name"): t for t in source.get("tables") or []}
    for name, expected in THRESHOLDS.items():
        freshness = {
            key: value
            for key, value in ((tables.get(name) or {}).get("freshness") or {}).items()
            if key != "filter"
        }
        if freshness != expected:
            problems.append(f"{name}: thresholds are {freshness}, expected {expected}")
    return problems


# -- fixtures for the wrong copies --------------------------------------------------------


def good_source():
    """A correct raw_feeds source, built from the design, so the wrong copies start right."""
    tables = []
    for feed, (name, endpoint) in MARKERS.items():
        tables.append(
            {
                "name": name,
                "identifier": "api_responses",
                "loaded_at_field": LOADED_AT,
                "freshness": {
                    **copy.deepcopy(THRESHOLDS[name]),
                    "filter": expected_filter(feed, endpoint),
                },
            }
        )
    return {"name": "raw_feeds", "schema": "raw", "tables": tables}


def good_captures():
    return [
        FixtureCapture("mlb", "schedule", {"season": "2026"}, "m/schedule"),
        FixtureCapture("mlb", "boxscore", {"season": "2026"}, "m/boxscore"),
        FixtureCapture("espn", "settings", {"league_id": "1", "season": "2026"}, "e/settings"),
        FixtureCapture("idmap", "player_id_map", {"provider": "sfbb"}, "i/player_id_map"),
    ]


def table_of(source, name):
    return next(t for t in source["tables"] if t["name"] == name)


# -- the committed declarations -----------------------------------------------------------


def test_the_fixtures_have_the_three_feeds():
    """Catches the fixtures being read as empty, which would make every fixture check vacuous."""
    assert {c.feed for c in fixture_captures()} == {"mlb", "espn", "idmap"}


def test_every_fixtured_feed_is_declared_and_no_other():
    """Catches a feed with fixtures and no freshness declaration, or a declaration left behind
    for a feed that is gone (R3.1)."""
    assert feed_problems(load_raw_feeds(), fixture_captures()) == []


def test_every_declared_endpoint_has_fixture_captures():
    """Catches a run marker misspelt or renamed, whose filter would then match no row (R3.2)."""
    assert endpoint_problems(load_raw_feeds(), fixture_captures()) == []


def test_every_filter_is_exactly_the_text_built_from_its_feed_and_endpoint():
    """Catches a copy-pasted declaration, or a season clause still naming the feed it was
    copied from, which would report another feed's age under this one's name (R3.3)."""
    assert filter_problems(load_raw_feeds()) == []


def test_the_source_reads_schema_raw_and_the_exact_timestamp_expression():
    """Catches a declaration that reads another relation or parses the stamp differently and
    still passes the filter checks (R3.4)."""
    assert config_problems(load_raw_feeds()) == []


def test_every_season_scoped_marker_capture_in_the_fixtures_has_a_year():
    """Catches a marker landed without a season, which the season clause would silently leave
    out; also fails while no declaration marks a season-scoped feed (R3.5)."""
    source = load_raw_feeds()
    scoped = [
        d for d in declared(source) if SEASON_PATH in collapse(table_filter(table_of(source, d[0])))
    ]
    assert {(feed, endpoint) for _name, feed, endpoint in scoped} == {
        ("mlb", "schedule"),
        ("espn", "settings"),
    }
    assert season_problems(source, fixture_captures()) == []


def test_the_run_markers_are_schedule_settings_and_player_id_map():
    """Catches a marker, or a declaration's name, changed without the spec (R1.1)."""
    assert marker_problems(load_raw_feeds()) == []


def test_raw_api_responses_has_no_freshness_of_its_own():
    """Catches the whole-table age coming back beside the three (R1.3)."""
    assert raw_table_problems(load_raw()) == []


def test_the_thresholds_are_the_designed_ones():
    """Catches a threshold changed without the spec, or an error threshold on the id map
    (R2.1, R2.2)."""
    assert threshold_problems(load_raw_feeds()) == []


# -- deliberately wrong copies: the helpers, not the files --------------------------------
# These pass now and later: they pin that each helper reports its fault.


def test_helpers_accept_a_correct_copy():
    """Catches a helper that reports a fault in a correct declaration (a false positive)."""
    source, captures = good_source(), good_captures()
    assert feed_problems(source, captures) == []
    assert endpoint_problems(source, captures) == []
    assert filter_problems(source) == []
    assert config_problems(source) == []
    assert season_problems(source, captures) == []
    assert marker_problems(source) == []
    assert threshold_problems(source) == []


def test_a_feed_with_fixtures_and_no_declaration_is_reported():
    """Catches feed_problems missing a feed that has fixtures and no declaration (R3.1)."""
    source = good_source()
    source["tables"].remove(table_of(source, "idmap_runs"))
    assert feed_problems(source, good_captures()) == ["feed idmap has fixtures and no declaration"]


def test_a_declaration_for_a_feed_with_no_fixtures_is_reported():
    """Catches feed_problems missing a declaration left behind for a feed that is gone (R3.1)."""
    problems = feed_problems(good_source(), good_captures()[:3])
    assert problems == ["feed idmap is declared but has no fixtures"]


def test_an_endpoint_without_fixture_captures_is_reported():
    """Catches endpoint_problems missing a misspelt marker (R3.2)."""
    source = good_source()
    table_of(source, "mlb_runs")["freshness"]["filter"] = expected_filter("mlb", "schedul")
    problems = endpoint_problems(source, good_captures())
    assert len(problems) == 1
    assert "schedul" in problems[0]


def test_a_season_clause_naming_another_feed_is_reported():
    """Catches filter_problems accepting a season subquery copied from another feed (R3.3)."""
    source = good_source()
    mlb_filter = table_of(source, "mlb_runs")["freshness"]["filter"]
    table_of(source, "espn_runs")["freshness"]["filter"] = mlb_filter.replace(
        "source = 'mlb' and endpoint = 'schedule' and",
        "source = 'espn' and endpoint = 'settings' and",
        1,
    )
    problems = filter_problems(source)
    assert len(problems) == 1
    assert problems[0].startswith("espn_runs:")


def test_a_filter_with_whitespace_differences_only_is_accepted():
    """Catches filter_problems comparing raw text, so that the YAML's line breaks fail (R3.3)."""
    source = good_source()
    spaced = table_of(source, "mlb_runs")["freshness"]
    spaced["filter"] = spaced["filter"].replace(" and ", "\n  and ").replace("( ", "(\n ")
    assert filter_problems(source) == []


def test_a_feed_declared_twice_and_a_missing_filter_are_reported():
    """Catches filter_problems letting a feed appear in two declarations, or a declaration
    with no filter at all (R3.3)."""
    source = good_source()
    twin = copy.deepcopy(table_of(source, "idmap_runs"))
    twin["name"] = "idmap_runs_again"
    source["tables"].append(twin)
    del table_of(source, "mlb_runs")["freshness"]["filter"]
    problems = filter_problems(source)
    assert "mlb_runs: has no freshness filter" in problems
    assert "feed idmap is declared 2 times" in problems


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (lambda s: s.update(schema="other"), "schema"),
        (lambda s: table_of(s, "mlb_runs").update(identifier="other"), "mlb_runs: identifier"),
        (
            lambda s: table_of(s, "espn_runs").update(loaded_at_field="strptime(fetched_at, '%Y')"),
            "espn_runs: loaded_at_field",
        ),
        (lambda s: table_of(s, "idmap_runs").pop("loaded_at_field"), "idmap_runs: loaded_at_field"),
    ],
    ids=["schema", "identifier", "loaded_at_field-changed", "loaded_at_field-missing"],
)
def test_a_wrong_schema_identifier_or_timestamp_is_reported(change, fragment):
    """Catches config_problems accepting another schema, relation or timestamp parse (R3.4)."""
    source = good_source()
    change(source)
    problems = config_problems(source)
    assert len(problems) == 1
    assert fragment in problems[0]


@pytest.mark.parametrize(
    "season", [None, "26", "2026-27", 26], ids=["absent", "two", "range", "int"]
)
def test_a_marker_capture_without_a_four_digit_season_is_reported(season):
    """Catches season_problems missing a marker landed with no season or a malformed one, which
    the season clause would silently leave out (R3.5)."""
    captures = good_captures()
    partitions = {} if season is None else {"season": season}
    captures[0] = FixtureCapture("mlb", "schedule", partitions, "m/schedule/bad")
    problems = season_problems(good_source(), captures)
    assert len(problems) == 1
    assert "mlb/schedule" in problems[0]
    assert "m/schedule/bad" in problems[0]


def test_a_capture_that_is_not_a_season_scoped_marker_is_not_checked():
    """Catches season_problems demanding a season of the id map or of a non-marker endpoint."""
    captures = good_captures() + [FixtureCapture("mlb", "players", {}, "m/players")]
    assert season_problems(good_source(), captures) == []


def test_a_changed_marker_is_reported():
    """Catches marker_problems missing a marker changed to another endpoint (R1.1)."""
    source = good_source()
    table_of(source, "espn_runs")["freshness"]["filter"] = expected_filter("espn", "teams")
    problems = marker_problems(source)
    assert len(problems) == 1
    assert "espn" in problems[0]


def test_api_responses_keeping_freshness_or_loaded_at_field_is_reported():
    """Catches raw_table_problems missing either key left on api_responses (R1.3)."""
    raw = {
        "name": "raw",
        "tables": [{"name": "api_responses", "freshness": {}, "loaded_at_field": "x"}],
    }
    assert len(raw_table_problems(raw)) == 2


def test_a_changed_threshold_and_an_idmap_error_threshold_are_reported():
    """Catches threshold_problems missing a changed count, or an error_after on the id map
    (R2.1, R2.2)."""
    source = good_source()
    table_of(source, "mlb_runs")["freshness"]["warn_after"]["count"] = 48
    table_of(source, "idmap_runs")["freshness"]["error_after"] = {"count": 30, "period": "day"}
    problems = threshold_problems(source)
    assert len(problems) == 2
    assert any(p.startswith("mlb_runs:") for p in problems)
    assert any(p.startswith("idmap_runs:") for p in problems)
