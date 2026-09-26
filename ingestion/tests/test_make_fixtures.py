"""Tests for the fixture builder's allowlist.

This is the mechanism that keeps other people's data out of a public repo, so it is
tested directly rather than trusted. The rule: a field nobody listed cannot appear in a
fixture, no matter where it sits in the payload.
"""

from make_fixtures import pick, rebuild


def test_rebuild_keeps_only_allowlisted_fields():
    source = {
        "gamePk": 1,
        "link": "/api/v1.1/game/1/feed/live",
        "status": {"abstractGameState": "Final", "codedGameState": "F"},
    }
    assert rebuild(source, ("gamePk", "status.abstractGameState")) == {
        "gamePk": 1,
        "status": {"abstractGameState": "Final"},
    }


def test_rebuild_drops_unlisted_nested_containers_entirely():
    source = {"teams": {"home": {"team": {"id": 5, "name": "X"}, "probablePitcher": {"id": 99}}}}
    rebuilt = rebuild(source, ("teams.home.team.id",))
    assert rebuilt == {"teams": {"home": {"team": {"id": 5}}}}
    assert "probablePitcher" not in rebuilt["teams"]["home"]
    assert "name" not in rebuilt["teams"]["home"]["team"]


def test_rebuild_skips_absent_fields_without_inventing_keys():
    # rescheduledFrom is present only on affected games; absence must not create a null.
    assert rebuild({"gamePk": 1}, ("gamePk", "rescheduledFrom")) == {"gamePk": 1}


def test_rebuild_of_an_espn_shaped_payload_omits_member_identity():
    """A shape resembling ESPN's: names and member GUIDs must not survive."""
    source = {
        "id": 7,
        "abbrev": "TM7",
        "name": "Real Team Name",
        "primaryOwner": "{ABC12345-1234-1234-1234-1234567890AB}",
        "members": [{"firstName": "A", "lastName": "B", "id": "{GUID}"}],
        "record": {"overall": {"wins": 15, "losses": 3}},
    }
    rebuilt = rebuild(source, ("id", "record.overall.wins", "record.overall.losses"))
    assert rebuilt == {"id": 7, "record": {"overall": {"wins": 15, "losses": 3}}}
    serialized = str(rebuilt)
    assert "Real Team Name" not in serialized
    assert "members" not in serialized
    assert "primaryOwner" not in serialized


def test_pick_returns_none_when_path_runs_into_a_non_dict():
    assert pick({"teams": [1, 2]}, "teams.home.id") is None
