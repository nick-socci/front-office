"""Committed fixtures must not carry other people's identities.

This repo is public. ESPN payloads contain league members' names and account GUIDs, and
those people never agreed to appear here. dbt's anonymize var protects query output; it
cannot protect a file on disk, so ESPN fixtures are anonymised when generated and this
test guards the result.

The checks are scoped to ESPN deliberately: MLB data is public, and MLB's gameGuid is a
legitimate GUID that would trip the pattern.
"""

import csv
import json
import re
from pathlib import Path

import pytest

from front_office.privacy import FORBIDDEN_KEYS, GUID, walk

REPO_ROOT = Path(__file__).resolve().parents[2]
# The combined fixture (spec 0028, R5.2) is held to every check the single one is.
FIXTURE_ROOTS = [REPO_ROOT / "fixtures/landing", REPO_ROOT / "fixtures/landing_multi"]
# Every capture is a directory holding payload.json and meta.json; both are scanned.
ESPN_FIXTURES = sorted(p for root in FIXTURE_ROOTS for p in (root / "espn").rglob("*.json"))
# Seeds are committed too, and the pre-commit guard is opt-in per clone, so CI checks them.
SEEDS = sorted((REPO_ROOT / "dbt/seeds").glob("*.csv"))

FIXTURE_TEAM_NAME = re.compile(r"^Team \d{2}$")


@pytest.mark.parametrize("root", FIXTURE_ROOTS, ids=lambda r: r.name)
def test_espn_fixtures_exist(root):
    """A privacy test that silently checks nothing is worse than no test."""
    assert list((root / "espn").rglob("*.json")), f"no ESPN fixtures under {root}; regenerate"


@pytest.mark.parametrize("root", FIXTURE_ROOTS, ids=lambda r: r.name)
def test_every_espn_payload_and_sidecar_is_scanned(root):
    """Catches a filename assumption (an old-layout `*.meta.json` pattern) leaving the new
    names unscanned: every file under espn/ is payload.json or meta.json, and each is in
    ESPN_FIXTURES, which the key and GUID tests below cover."""
    files = [p for p in (root / "espn").rglob("*") if p.is_file()]
    assert {p.name for p in files} == {"payload.json", "meta.json"}
    assert set(files) <= set(ESPN_FIXTURES)


@pytest.mark.parametrize("path", ESPN_FIXTURES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_person_identifying_keys(path):
    for _, key, _ in walk(json.loads(path.read_text())):
        assert key not in FORBIDDEN_KEYS, f"{path}: forbidden key {key!r}"


@pytest.mark.parametrize("path", ESPN_FIXTURES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_account_guids(path):
    match = GUID.search(path.read_text())
    assert match is None, f"{path}: looks like an ESPN account id: {match.group() if match else ''}"


def test_seeds_exist():
    assert SEEDS, "no seeds found under dbt/seeds"


@pytest.mark.parametrize("path", SEEDS, ids=lambda p: p.name)
def test_seeds_carry_no_member_columns_or_guids(path):
    text = path.read_text()
    header = next(csv.reader([text.splitlines()[0]]))
    assert not set(header) & FORBIDDEN_KEYS, f"{path}: forbidden column(s)"
    match = GUID.search(text)
    assert match is None, f"{path}: looks like an ESPN account id: {match.group() if match else ''}"


@pytest.mark.parametrize("root", FIXTURE_ROOTS, ids=lambda r: r.name)
def test_team_names_are_aliases(root):
    """Real team names are chosen by real people and must not be committed."""
    teams_fixtures = [
        p
        for p in (root / "espn").rglob("*.json")
        if "/teams/" in str(p) and p.name == "payload.json"
    ]
    assert teams_fixtures, "no ESPN teams fixture found"
    for path in teams_fixtures:
        for team in json.loads(path.read_text())["teams"]:
            assert FIXTURE_TEAM_NAME.match(team["name"]), f"{path}: real team name {team['name']!r}"
            assert team["abbrev"].startswith("T"), f"{path}: real abbrev {team['abbrev']!r}"


@pytest.mark.parametrize("root", FIXTURE_ROOTS, ids=lambda r: r.name)
def test_league_name_is_a_placeholder(root):
    settings = [
        p
        for p in (root / "espn").rglob("*.json")
        if "/settings/" in str(p) and p.name == "payload.json"
    ]
    assert settings, "no ESPN settings fixture found"
    for path in settings:
        name = json.loads(path.read_text())["settings"]["name"]
        assert name == "Fixture League", f"{path}: real league name {name!r}"


# --- the guards must actually catch violations, or they are decoration ---


def test_guid_pattern_catches_a_real_shaped_account_id():
    assert GUID.search('"primaryOwner": "{272E019C-48D5-42F3-B289-C48A1B163E19}"')
    assert GUID.search("272E019C-48D5-42F3-B289-C48A1B163E19")


def test_guid_pattern_ignores_ordinary_ids():
    assert GUID.search('{"playerId": 4719324, "teamId": 7}') is None


def test_walk_finds_a_forbidden_key_nested_deep():
    payload = {"teams": [{"roster": {"entries": [{"playerPoolEntry": {"members": ["x"]}}]}}]}
    keys = {key for _, key, _ in walk(payload)}
    assert keys & FORBIDDEN_KEYS == {"members"}
