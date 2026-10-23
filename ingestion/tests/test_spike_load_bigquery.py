"""The spike's loader: what may leave the machine, and whether it arrived whole (spec 0130,
R3; ADR 0054).

Nothing here talks to BigQuery. The privacy check and the row comparison are pure
functions over rows; the reading of the manifest and the landing zone is tested on a small
landing root and DuckDB file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import duckdb
import pytest

import spike_load_bigquery as loader
from front_office.landing import LandingZone
from front_office.load import load_landing_zone

GUID = "{272E019C-48D5-42F3-B289-C48A1B163E19}"
# Another account id, and the normal form (braces stripped, lower case) of both: the form in
# which the check keeps the known accounts.
OTHER_GUID = "{A1B2C3D4-0000-4000-8000-0123456789AB}"
ACCOUNTS = frozenset({"272e019c-48d5-42f3-b289-c48a1b163e19"})


def row(source: str, endpoint: str, payload: object, **overrides: str) -> loader.RawRow:
    values = {
        "source": source,
        "endpoint": endpoint,
        "request_path": "/a/path",
        "request_key": "k=1",
        "fetched_at": "20260926T162307Z",
        "file_path": f"data/raw/{source}/{endpoint}/payload.json",
        "partitions": "{}",
        "payload": json.dumps(payload),
    }
    values.update(overrides)
    return loader.RawRow(**values)


# -- the privacy check (R3.3) ------------------------------------------------------------


def test_a_guid_in_an_espn_row_stops_the_upload_and_the_value_is_not_reported() -> None:
    """Catches an ESPN account id going up, and the check printing the id it found."""
    hits = loader.privacy_hits(row("espn", "roster", {"teams": [{"note": f"by {GUID}"}]}), ACCOUNTS)
    assert hits == ["espn/roster k=1: GUID at $.teams[0].note"]
    assert GUID not in "".join(hits)


def test_a_guid_as_a_key_or_outside_the_payload_is_found_too() -> None:
    """Catches a GUID that is a key of an object, or in the partitions, slipping through a
    check that reads only values of the payload."""
    as_key = loader.privacy_hits(row("espn", "settings", {"byOwner": {GUID: 1}}), ACCOUNTS)
    assert as_key == ["espn/settings k=1: GUID in a key at $.byOwner"]
    in_partitions = loader.privacy_hits(
        row("espn", "settings", {}, partitions=json.dumps({"owner": GUID})), ACCOUNTS
    )
    assert in_partitions == ["espn/settings k=1: GUID at partitions $.owner"]


def test_a_guid_in_the_request_key_is_not_printed_by_any_message_about_the_row() -> None:
    """Catches the row's label carrying a value: a row keyed by an account id that is
    rejected for something else would print the id in every message about it (PR #142,
    review round 1)."""
    keyed = row("espn", "roster", {"members": []}, request_key=f"owner={GUID}&view=mRoster")
    hits = loader.privacy_hits(keyed, ACCOUNTS)
    assert hits, "the row should be rejected"
    assert GUID not in "".join(hits)
    assert any("owner=<guid>&view=mRoster" in hit for hit in hits)
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.check([keyed], ACCOUNTS)
    assert GUID not in "".join(raised.value.hits) + str(raised.value)


def test_a_guid_that_is_a_key_on_the_way_to_a_hit_is_not_printed_in_the_path() -> None:
    """Catches a path carrying a value: a path is made of the document's keys, so a hit
    found under an object keyed by account id would print the id (PR #142, review round
    2)."""
    nested = row("espn", "settings", {"byOwner": {GUID: {"members": [], "note": f"x {GUID}"}}})
    hits = loader.privacy_hits(nested, ACCOUNTS)
    assert len(hits) >= 3, hits
    assert GUID not in "".join(hits)
    assert any("$.byOwner.<guid>" in hit for hit in hits)


def test_mlbs_game_guid_is_allowed() -> None:
    """Catches the GUID rule reaching MLB rows, where gameGuid is a public game id and every
    schedule row would be refused."""
    schedule = {"dates": [{"games": [{"gameGuid": "272e019c-48d5-42f3-b289-c48a1b163e19"}]}]}
    assert loader.privacy_hits(row("mlb", "schedule", schedule), ACCOUNTS) == []


def test_a_members_name_stops_the_upload() -> None:
    """Catches a league member's name going up: a forbidden key is a hit in any row."""
    payload = {"members": [{"firstName": "A", "lastName": "B"}]}
    assert loader.privacy_hits(row("espn", "settings", payload), ACCOUNTS) == [
        "espn/settings k=1: key members at $",
        "espn/settings k=1: key firstName at $.members[0]",
        "espn/settings k=1: key lastName at $.members[0]",
    ]
    assert loader.privacy_hits(row("mlb", "schedule", {"displayName": "x"}), ACCOUNTS) == [
        "mlb/schedule k=1: key displayName at $"
    ]


def test_a_ballplayers_own_name_is_allowed_and_nothing_else_in_that_object() -> None:
    """Catches the one exception widening: firstName and lastName directly in a
    playerPoolEntry.player object name a ballplayer; an owner there, or a name one level
    further in, does not."""
    player = {"firstName": "Shohei", "lastName": "Ohtani", "id": 39832}
    entry = {"teams": [{"roster": {"entries": [{"playerPoolEntry": {"player": player}}]}}]}
    assert loader.privacy_hits(row("espn", "roster", entry), ACCOUNTS) == []

    player_with_owner = {**player, "owners": ["x"]}
    entry = {"playerPoolEntry": {"player": player_with_owner}}
    assert loader.privacy_hits(row("espn", "roster", entry), ACCOUNTS) == [
        "espn/roster k=1: key owners at $.playerPoolEntry.player"
    ]
    deeper = {"playerPoolEntry": {"player": {"agent": {"firstName": "A"}}}}
    assert loader.privacy_hits(row("espn", "roster", deeper), ACCOUNTS) == [
        "espn/roster k=1: key firstName at $.playerPoolEntry.player.agent"
    ]
    elsewhere = {"player": {"firstName": "A"}}
    assert loader.privacy_hits(row("espn", "roster", elsewhere), ACCOUNTS) == [
        "espn/roster k=1: key firstName at $.player"
    ]


def _landing(
    tmp_path: Path, captures: list[tuple[str, str, str, object]], *, load: bool = True
) -> tuple[Path, Path]:
    """A landing root of committed captures and a warehouse whose raw.captures lists them
    (made by the real loader). Each capture is (source, endpoint, key, payload)."""
    zone = LandingZone(tmp_path / "raw")
    for number, (source, endpoint, key, payload) in enumerate(captures):
        stamp = f"20260926T1623{number:02d}Z"
        zone.write(
            source=source,
            endpoint=endpoint,
            partitions={"season": 2025},
            name=f"fetched_at={stamp}",
            payload=payload,  # type: ignore[arg-type]
            request={"url": f"https://x.test/{key}", "params": {"k": key}},
            fetched_at=stamp,
        )
    db = tmp_path / "w.duckdb"
    con = duckdb.connect(str(db))
    if load:
        load_landing_zone(con, zone)
    con.close()
    return db, zone.root


LISTED = {
    ("mlb", "boxscore"),
    ("mlb", "schedule"),
    ("mlb", "players"),
    ("espn", "roster"),
    ("espn", "matchups"),
    ("espn", "settings"),
    ("espn", "pro_schedule"),
    ("espn", "teams"),
    ("espn", "transactions"),
    ("espn", "matchup_days"),
    ("idmap", "player_id_map"),
}


def test_only_the_listed_endpoints_are_read(tmp_path: Path) -> None:
    """Catches an endpoint being read that no ADR allows (here `espn/draft`), and one of the
    eleven (ADRs 0054, 0061, 0093, 0095) being left out, in particular `mlb/players`."""
    pairs = [*sorted(LISTED), ("espn", "draft")]
    db, root = _landing(tmp_path, [(s, e, f"k{n}", {"n": 1}) for n, (s, e) in enumerate(pairs)])
    rows = list(loader.read_rows(db, root))
    assert sorted((r.source, r.endpoint) for r in rows) == sorted(LISTED)
    assert len(rows) == 11
    assert set(loader.UPLOADED) == LISTED
    assert set(loader.ALLOWLIST) == LISTED - {
        ("espn", "teams"),
        ("espn", "transactions"),
        ("espn", "matchup_days"),
    }


def test_a_row_off_the_allowlist_stops_the_upload_however_clean_it_is() -> None:
    """Catches the second guard going: reading takes only the listed endpoints, and the
    check refuses any other row it is handed, so a caller that builds its own rows cannot
    upload `draft`."""
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.check([row("espn", "draft", {"teams": []})], ACCOUNTS)
    assert any("not on the allowlist" in hit for hit in raised.value.hits)
    assert loader.check([row("espn", "settings", {"teams": []})], ACCOUNTS) == {
        ("espn", "settings"): 1
    }


def test_a_hit_anywhere_means_nothing_is_written(tmp_path: Path) -> None:
    """Catches files being exported for the clean endpoints before a hit in another is
    found: on any hit nothing is written at all."""
    clean = row("mlb", "schedule", {"dates": []})
    dirty = row("espn", "settings", {"members": []}, request_key="k=2")
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.export([clean, dirty], tmp_path / "out", ACCOUNTS)
    assert raised.value.hits == ["espn/settings k=2: key members at $"]
    assert not (tmp_path / "out").exists()


def test_the_export_is_one_file_per_endpoint_with_json_as_json(tmp_path: Path) -> None:
    """Catches a payload written as a quoted string, which would load as a JSON string and
    not an object, or two endpoints sharing a file."""
    rows = [
        row("mlb", "schedule", {"dates": [1.5]}),
        row("espn", "settings", {"id": 7}, request_key="k=2", partitions='{"season": 2026}'),
    ]
    files = loader.export(rows, tmp_path / "out", ACCOUNTS)
    assert sorted(p.name for p in files) == ["espn__settings.ndjson", "mlb__schedule.ndjson"]
    line = json.loads((tmp_path / "out" / "espn__settings.ndjson").read_text())
    assert line["payload"] == {"id": 7} and line["partitions"] == {"season": 2026}
    assert line["request_key"] == "k=2" and set(line) == set(loader.COLUMNS)


# -- the comparison after the load (R3.4) ------------------------------------------------


def loaded(source_row: loader.RawRow, **changes: object) -> dict[str, object]:
    """The row as BigQuery would give it back: JSON columns parsed."""
    back: dict[str, object] = {
        **{name: getattr(source_row, name) for name in loader.KEY_COLUMNS},
        "file_path": source_row.file_path,
        "partitions": json.loads(source_row.partitions),
        "payload": json.loads(source_row.payload),
    }
    back.update(changes)
    return back


def test_rows_that_came_back_the_same_are_equal_whatever_the_key_order_or_number_form() -> None:
    """Catches a comparison of text: the two warehouses write the same JSON differently."""
    source = row("espn", "settings", {"a": 1, "b": [1.0, 2.5], "c": {"x": None}})
    back = loaded(source, payload={"c": {"x": None}, "b": [1, 2.5], "a": 1.0})
    as_text = loaded(source, payload='{"b": [1, 2.5], "a": 1, "c": {"x": null}}')
    for other in (back, as_text):
        result = loader.compare_rows([source], [other])
        assert result == {("espn", "settings"): loader.Tally(paired=1, equal=1)}
        assert loader.all_equal(result)


def test_a_payload_that_lost_or_changed_one_field_is_not_equal() -> None:
    """Catches what a row count would pass: a field dropped, changed, or a number rounded."""
    source = row("espn", "settings", {"a": 1, "b": {"c": 0.1234567890123}})
    for payload in ({"a": 1}, {"a": 2, "b": {"c": 0.1234567890123}}, {"a": 1, "b": {"c": 0.1234}}):
        result = loader.compare_rows([source], [loaded(source, payload=payload)])
        assert result == {("espn", "settings"): loader.Tally(paired=1, equal=0)}
        assert not loader.all_equal(result)


def test_a_different_file_path_or_partitions_is_not_equal() -> None:
    """Catches a changed file_path, the tie-break of fo_espn_latest, or changed partitions,
    which staging reads the league and season from."""
    source = row("espn", "roster", {"a": 1}, partitions='{"season": 2026}')
    for change in ({"file_path": "elsewhere"}, {"partitions": {"season": 2025}}):
        result = loader.compare_rows([source], [loaded(source, **change)])
        assert result[("espn", "roster")] == loader.Tally(paired=1, equal=0)


def test_a_row_on_one_side_only_is_counted_and_fails() -> None:
    """Catches a row that never arrived, and one that arrived from nowhere."""
    first = row("mlb", "boxscore", {"a": 1}, request_key="gamePk=1")
    second = row("mlb", "boxscore", {"a": 2}, request_key="gamePk=2")
    stray = loaded(row("mlb", "boxscore", {"a": 3}, request_key="gamePk=3"))
    result = loader.compare_rows([first, second], [loaded(first), stray])
    assert result == {
        ("mlb", "boxscore"): loader.Tally(paired=1, equal=1, only_source=1, only_loaded=1)
    }
    assert not loader.all_equal(result)
    assert not loader.all_equal(loader.compare_rows([first], []))


def test_the_same_key_loaded_twice_is_not_a_pair() -> None:
    """Catches a load that appended to a table it should have replaced: the second copy of
    a row has no source row left to pair with."""
    source = row("mlb", "boxscore", {"a": 1})
    result = loader.compare_rows([source], [loaded(source), loaded(source)])
    assert result[("mlb", "boxscore")] == loader.Tally(paired=1, equal=1, only_loaded=1)


# -- the two endpoints uploaded as projections (ADR 0061) ------------------------------------

MEMBER = {"firstName": "A", "lastName": "Member", "id": GUID}
MATCHUP_DAY = {
    "id": 73677,
    "seasonId": 2025,
    "scoringPeriodId": 12,
    "status": {"currentMatchupPeriod": 2},
    "members": [MEMBER],
    "teams": [{"id": 1, "owners": [GUID], "primaryOwner": GUID}],
    "settings": {"name": "League"},
    "schedule": [
        {
            "id": 7,
            "matchupPeriodId": 2,
            "winner": "HOME",
            "home": {
                "teamId": 1,
                "totalPoints": 5,
                "rosterForCurrentScoringPeriod": {
                    "entries": [{"playerId": 9, "playerPoolEntry": {"player": {"firstName": "B"}}}]
                },
                "rosterForMatchupPeriod": {
                    "entries": [
                        {
                            "playerId": 9,
                            "lineupSlotId": 0,
                            "injuryStatus": "ACTIVE",
                            "playerPoolEntry": {
                                "id": 9,
                                "onTeamId": 1,
                                "player": {
                                    "id": 9,
                                    "firstName": "B",
                                    "lastName": "Ballplayer",
                                    "fullName": "B Ballplayer",
                                    "displayName": "B",
                                    "stats": [
                                        {
                                            "id": "05null",
                                            "seasonId": 2025,
                                            "statSourceId": 0,
                                            "statSplitTypeId": 5,
                                            "scoringPeriodId": 0,
                                            "stats": {"1": 3.0, "2": "n/a"},
                                        },
                                        {
                                            "statSourceId": 1,
                                            "statSplitTypeId": 5,
                                            "scoringPeriodId": 0,
                                            "stats": {"1": 9.0, "nested": {"owners": [GUID]}},
                                        },
                                    ],
                                },
                            },
                        }
                    ]
                },
            },
            "away": {
                "teamId": 2,
                "totalPoints": 4,
                "rosterForCurrentScoringPeriod": {"entries": []},
                "rosterForMatchupPeriod": {"entries": []},
            },
        },
        {"id": 8, "matchupPeriodId": 3, "home": {"teamId": 3}},
        {"id": 9, "matchupPeriodId": 1, "home": {"teamId": 4}, "away": {"teamId": 5}},
    ],
}


PROJECTED_FIRST_MATCHUP = {
    "id": 7,
    "matchupPeriodId": 2,
    "home": {
        "teamId": 1,
        "rosterForCurrentScoringPeriod": {},
        "rosterForMatchupPeriod": {
            "entries": [
                {
                    "playerId": 9,
                    "playerPoolEntry": {
                        "player": {
                            "stats": [
                                {
                                    "statSourceId": 0,
                                    "statSplitTypeId": 5,
                                    "scoringPeriodId": 0,
                                    "stats": {"1": 3.0, "2": "n/a"},
                                },
                                {
                                    "statSourceId": 1,
                                    "statSplitTypeId": 5,
                                    "scoringPeriodId": 0,
                                    "stats": {"1": 9.0},
                                },
                            ]
                        }
                    },
                }
            ]
        },
    },
    "away": {
        "teamId": 2,
        "rosterForCurrentScoringPeriod": {},
        "rosterForMatchupPeriod": {"entries": []},
    },
}


def test_a_matchup_day_goes_up_as_the_fields_its_models_read() -> None:
    """Catches a field outside ADR 0061's list being uploaded (the response holds `teams`,
    `members` and `settings`), and one it lists being lost: the ids, each matchup's id and
    period, the marker's presence on each side as an empty object, and (spec 0147) the
    side's team and ESPN's matchup lines: each entry's player id and its stat lines' four
    fields. Also a matchup's `id` being dropped, which stg_espn__matchup_player_lines
    needs to say which matchup a line belongs to."""
    projected = loader.project_matchup_day(MATCHUP_DAY)
    assert projected == {
        "id": 73677,
        "seasonId": 2025,
        "scoringPeriodId": 12,
        "schedule": [
            PROJECTED_FIRST_MATCHUP,
            {"id": 8, "matchupPeriodId": 3},
            {"id": 9, "matchupPeriodId": 1},
        ],
    }
    assert [m["id"] for m in projected["schedule"]] == [7, 8, 9]


def test_a_projected_matchup_day_holds_no_name_and_no_member_key() -> None:
    """Catches a name or a member key reaching BigQuery through the matchup lines (spec
    0147, R1.4): the player objects carry `firstName`, `lastName`, `fullName` and
    `displayName`, and the response holds `members`, `owners` and an account id. Walks
    every key of the projection for the patterns of front_office/privacy.py, as the
    upload's check does, and for the other name keys and `lineupSlotId` the projection
    does not list."""
    from front_office import privacy

    text = json.dumps(loader.project_matchup_day(MATCHUP_DAY))
    keys = {key for _, key, _ in privacy.walk(json.loads(text))}
    assert not keys & privacy.FORBIDDEN_KEYS
    assert not keys & {"fullName", "lineupSlotId", "injuryStatus", "teams", "settings", "nested"}
    assert not privacy.GUID.search(text)
    assert loader.privacy_hits(row("espn", "matchup_days", json.loads(text)), ACCOUNTS) == []


def test_a_projection_is_built_from_wanted_fields_so_an_unknown_one_is_dropped() -> None:
    """Catches a projection made by removing known member keys: a key ESPN adds tomorrow
    must not go up because nobody listed it."""
    grown = {**MATCHUP_DAY, "newThing": {"author": GUID}}
    grown["schedule"] = [{**MATCHUP_DAY["schedule"][0], "alsoNew": GUID}]  # type: ignore[dict-item]
    projected = loader.project_matchup_day(grown)
    assert GUID not in json.dumps(projected) and "newThing" not in projected
    assert projected["schedule"] == [PROJECTED_FIRST_MATCHUP]


def test_a_payload_of_an_unexpected_shape_projects_to_what_it_can() -> None:
    """Catches the projection crashing, or passing a value through, when ESPN answers with
    something else: no schedule, a schedule that is not a list, a side that is not an
    object."""
    assert loader.project_matchup_day({"id": 1}) == {"id": 1, "schedule": []}
    assert loader.project_matchup_day({"schedule": "x"}) == {"schedule": []}
    assert loader.project_matchup_day({"schedule": [{"home": GUID}, GUID]}) == {
        "schedule": [{}, {}]
    }
    assert loader.project_matchup_day([GUID]) == {"schedule": []}


TEAMS = {
    "id": 73677,
    "seasonId": 2025,
    "gameId": 1,
    "members": [MEMBER],
    "status": {"currentMatchupPeriod": 2},
    "teams": [
        {
            "id": 1,
            "abbrev": "ABC",
            "name": "The Team",
            "logo": "https://x.test/logo.png",
            "owners": [GUID],
            "primaryOwner": GUID,
            "playoffSeed": 2,
            "eliminated": False,
            "unknownKey": {"author": GUID},
            "record": {
                "overall": {
                    "wins": 10,
                    "losses": 4,
                    "ties": 1,
                    "streakLength": 3,
                    "streakType": "WIN",
                    "pointsFor": 1234.5,
                },
                "home": {"wins": 5},
            },
        },
        {"id": 2, "name": "Another"},
    ],
}
PROJECTED_TEAMS = {
    "id": 73677,
    "seasonId": 2025,
    "teams": [
        {
            "id": 1,
            "abbrev": "ABC",
            "name": "The Team",
            "playoffSeed": 2,
            "eliminated": False,
            "record": {
                "overall": {
                    "wins": 10,
                    "losses": 4,
                    "ties": 1,
                    "streakLength": 3,
                    "streakType": "WIN",
                }
            },
        },
        {"id": 2, "name": "Another"},
    ],
}
TOPIC_ID = "5b1c0f3e-0a8e-4d2c-9e57-0c5f6a1b2d3e"
MESSAGE_ID = "0e9d8c7b-6a5f-4e3d-8c2b-1a0f9e8d7c6b"
TRANSACTIONS = {
    "status": {"x": 1},
    "topics": [
        {
            "id": TOPIC_ID,
            "date": 1700000000000,
            "author": GUID,
            "creationInfo": {"source": GUID},
            "unknownKey": 1,
            "messages": [
                {
                    "id": MESSAGE_ID,
                    "date": 1700000000001,
                    "messageTypeId": 178,
                    "targetId": 39832,
                    "to": 3,
                    "from": 4,
                    "for": 1,
                    "author": GUID,
                    "topicId": TOPIC_ID,
                    "creationInfo": {"source": GUID},
                    "unknownKey": GUID,
                }
            ],
        }
    ],
}
PROJECTED_TRANSACTIONS = {
    "topics": [
        {
            "id": TOPIC_ID,
            "date": 1700000000000,
            "messages": [
                {
                    "id": MESSAGE_ID,
                    "date": 1700000000001,
                    "messageTypeId": 178,
                    "targetId": 39832,
                    "to": 3,
                    "from": 4,
                    "for": 1,
                }
            ],
        }
    ]
}


def test_a_team_goes_up_as_the_fixtures_team_fields() -> None:
    """Catches anything beyond the fixtures' ESPN_TEAM_FIELDS going up (the response holds
    `members`, `owners`, `primaryOwner`, a logo and a key nobody listed), a wanted field
    being lost, and the loader keeping a list of its own: the list is the fixtures' tuple
    itself (ADR 0093, R1.4)."""
    import make_fixtures

    assert loader.ESPN_TEAM_FIELDS is make_fixtures.ESPN_TEAM_FIELDS
    projected = loader.project_teams(TEAMS)
    assert projected == PROJECTED_TEAMS
    text = json.dumps(projected)
    assert GUID not in text and "members" not in projected and "owners" not in text


def test_a_transaction_goes_up_as_its_ids_and_message_fields() -> None:
    """Catches `author`, `creationInfo`, `topicId` or an unlisted key going up from a
    transaction log, and a field staging reads (a topic's id and date, a message's id and
    the fixtures' ESPN_TRANSACTION_MESSAGE_FIELDS) being lost (ADR 0093, R1.3, R1.4)."""
    import make_fixtures

    assert loader.ESPN_TRANSACTION_MESSAGE_FIELDS is make_fixtures.ESPN_TRANSACTION_MESSAGE_FIELDS
    projected = loader.project_transactions(TRANSACTIONS)
    assert projected == PROJECTED_TRANSACTIONS
    assert GUID not in json.dumps(projected)


def test_a_nested_value_at_a_wanted_field_is_dropped() -> None:
    """Catches an object or array smuggled in under a wanted name (`name: {firstName: …}`,
    a `to` that is a list, `record.overall` that is an array): the projection keeps single
    values only, where fixtures' `rebuild` copies whatever it finds (R1.5)."""
    team = {
        "id": 1,
        "name": {"firstName": "A", "owners": [GUID]},
        "abbrev": [GUID],
        "record": {"overall": {"wins": {"x": 1}, "losses": 2}},
    }
    projected = loader.project_teams({"id": {"x": GUID}, "seasonId": [1], "teams": [team]})
    assert projected == {"teams": [{"id": 1, "record": {"overall": {"losses": 2}}}]}

    message = {"id": MESSAGE_ID, "to": {"author": GUID}, "from": [GUID], "for": None, "date": 5}
    topic = {"id": {"author": GUID}, "date": [1], "messages": [message]}
    assert loader.project_transactions({"topics": [topic]}) == {
        "topics": [{"messages": [{"id": MESSAGE_ID, "for": None, "date": 5}]}]
    }


def test_a_teams_or_transactions_payload_of_an_unexpected_shape_projects_to_what_it_can() -> None:
    """Catches the projection crashing, or passing a value through, when ESPN answers with
    something else: no teams, teams that are not a list, no topics, messages that are not a
    list, a payload that is not an object."""
    assert loader.project_teams({"id": 1}) == {"id": 1, "teams": []}
    assert loader.project_teams({"teams": GUID}) == {"teams": []}
    assert loader.project_teams([GUID]) == {"teams": []}
    assert loader.project_transactions({"topics": "x"}) == {"topics": []}
    assert loader.project_transactions([GUID]) == {"topics": []}
    assert loader.project_transactions({"topics": [{"id": TOPIC_ID, "messages": GUID}]}) == {
        "topics": [{"id": TOPIC_ID, "messages": []}]
    }


def test_the_three_endpoints_are_read_already_projected_and_pass_the_check(tmp_path: Path) -> None:
    """Catches the raw payload of any of the three endpoints reaching the check, the export
    or the read-back comparison: what is read for upload is the projection, so every later
    step sees only that. Also `mlb/players` being projected: it goes up whole (ADR 0095)."""
    people = {"people": [{"id": 1, "fullName": "A Player", "firstName": "A", "extra": [1]}]}
    db, root = _landing(
        tmp_path,
        [
            ("espn", "transactions", "k1", TRANSACTIONS),
            ("espn", "matchup_days", "scoringPeriodId=12", MATCHUP_DAY),
            ("espn", "settings", "k3", {"n": 1}),
            ("espn", "teams", "k4", TEAMS),
            ("mlb", "players", "k5", people),
        ],
    )
    rows = {(r.source, r.endpoint): r for r in loader.read_rows(db, root)}
    assert sorted(rows) == [
        ("espn", "matchup_days"),
        ("espn", "settings"),
        ("espn", "teams"),
        ("espn", "transactions"),
        ("mlb", "players"),
    ]
    assert json.loads(rows[("espn", "transactions")].payload) == PROJECTED_TRANSACTIONS
    assert json.loads(rows[("espn", "teams")].payload) == PROJECTED_TEAMS
    assert json.loads(rows[("espn", "matchup_days")].payload) == loader.project_matchup_day(
        MATCHUP_DAY
    )
    assert json.loads(rows[("espn", "settings")].payload) == {"n": 1}
    assert json.loads(rows[("mlb", "players")].payload) == people
    assert json.loads(rows[("espn", "transactions")].partitions) == {"season": 2025}
    assert set(loader.PROJECTIONS) == {
        ("espn", "teams"),
        ("espn", "transactions"),
        ("espn", "matchup_days"),
    }


# -- the manifest and the landing zone must agree (spec 0150, R5.2) ---------------------------


def test_the_uploaded_file_path_is_the_manifests_relative_path(tmp_path: Path) -> None:
    """Catches an absolute or cwd-dependent path being uploaded: the BigQuery capture views
    must tie-break on the same file_path text as the DuckDB ones."""
    db, root = _landing(tmp_path, [("espn", "settings", "k1", {"n": 1})])
    (found,) = loader.read_rows(db, root)
    con = duckdb.connect(str(db), read_only=True)
    (recorded,) = con.execute("select file_path from raw.captures").fetchone() or ("",)
    con.close()
    assert found.file_path == recorded
    assert found.file_path.startswith("espn/settings/season=2025/")
    assert found.file_path.endswith("/fetched_at=20260926T162300Z/payload.json")
    assert not Path(found.file_path).is_absolute()


def test_the_rows_can_be_read_more_than_once_in_key_order(tmp_path: Path) -> None:
    """Catches a single-use iterator: the check reads the rows, then the export does."""
    db, root = _landing(
        tmp_path,
        [("mlb", "schedule", "b", {"n": 2}), ("mlb", "schedule", "a", {"n": 1})],
    )
    rows = loader.read_rows(db, root)
    first = [r.request_key for r in rows]
    assert first == sorted(first) and len(first) == 2
    assert [r.request_key for r in rows] == first


def test_a_manifest_row_with_no_committed_capture_stops_the_upload(tmp_path: Path) -> None:
    """Catches an upload that skips a capture dbt would read."""
    db, root = _landing(tmp_path, [("espn", "settings", "k1", {"n": 1})])
    shutil.rmtree(next(root.glob("espn/settings/*/*")))
    with pytest.raises(loader.ManifestDisagrees) as raised:
        loader.check(loader.read_rows(db, root), ACCOUNTS)
    assert "in raw.captures, not committed: espn/settings/" in str(raised.value)


def test_a_committed_capture_not_in_the_manifest_stops_the_upload(tmp_path: Path) -> None:
    """Catches an upload of a capture dbt would not read."""
    db, root = _landing(tmp_path, [("espn", "settings", "k1", {"n": 1})])
    LandingZone(root).write(
        source="espn",
        endpoint="settings",
        partitions={"season": 2025},
        name="fetched_at=20270101T000000Z",
        payload={"n": 2},
        request={"url": "https://x.test/k2", "params": {"k": "k2"}},
        fetched_at="20270101T000000Z",
    )
    with pytest.raises(loader.ManifestDisagrees) as raised:
        loader.check(loader.read_rows(db, root), ACCOUNTS)
    assert "committed, not in raw.captures: espn/settings/" in str(raised.value)


def test_a_row_of_a_projected_endpoint_that_was_not_projected_stops_the_upload() -> None:
    """Catches a caller handing the check a whole capture of one of the two endpoints, even
    one with nothing the privacy patterns know: only the projection may go up."""
    whole = row("espn", "matchup_days", {"id": 1, "schedule": [], "status": {"x": 1}})
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.check([whole], ACCOUNTS)
    assert raised.value.hits == ["espn/matchup_days k=1: not what its projection would produce"]
    projected = row("espn", "matchup_days", loader.project_matchup_day(MATCHUP_DAY))
    assert loader.check([projected], ACCOUNTS) == {("espn", "matchup_days"): 1}


def test_a_whole_teams_or_transactions_capture_is_refused() -> None:
    """Catches a raw capture of `espn/teams` or `espn/transactions` reaching the export when
    a caller builds its own rows: a whole capture is refused as not in its projected form
    (R2.5), not only by the key and GUID patterns. A teams row is refused for that reason
    and not for being off the allowlist."""
    for endpoint, whole in (("teams", TEAMS), ("transactions", TRANSACTIONS)):
        with pytest.raises(loader.PrivacyHit) as raised:
            loader.check([row("espn", endpoint, whole)], ACCOUNTS)
        assert any("not what its projection would produce" in hit for hit in raised.value.hits)
        assert not any("allowlist" in hit for hit in raised.value.hits)
        assert GUID not in "".join(raised.value.hits)
    # nothing the privacy patterns know, and still refused
    clean = {"id": 1, "teams": [{"id": 1, "logo": "x"}]}
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.check([row("espn", "teams", clean)], ACCOUNTS)
    assert raised.value.hits == ["espn/teams k=1: not what its projection would produce"]


def test_a_guid_left_in_a_projected_row_still_stops_the_upload() -> None:
    """Catches the projection being trusted in place of the check: an account id in the
    request key of a projected row is found like any other."""
    dirty = row("espn", "transactions", {}, request_key=f"owner={GUID}")
    with pytest.raises(loader.PrivacyHit):
        loader.check([dirty], ACCOUNTS)


# -- the member-data endpoints: names in MLB's player list, transaction ids (ADRs 0094, 0095) --

BARE_ACCOUNT = "272e019c-48d5-42f3-b289-c48a1b163e19"  # the account of GUID, as ESPN's ids look


def transactions_row(topic_id: str, message_id: str = "m-1", **overrides: str) -> loader.RawRow:
    """A transactions row in projected form, with one topic and one message."""
    payload = {"topics": [{"id": topic_id, "messages": [{"id": message_id}]}]}
    return row("espn", "transactions", payload, **overrides)


def test_a_ballplayers_name_in_the_mlb_player_list_is_allowed_and_nowhere_else() -> None:
    """Catches the name exception widening past one endpoint, one place and two keys:
    `firstName` directly in an object of `$.people[]` of `mlb/players` passes. At
    `$.people[0].currentTeam`, at `$.firstName`, in another MLB endpoint, in an ESPN
    endpoint of the same name, and `displayName` in `people[0]` each stop the upload (R2.1,
    ADR 0095)."""
    person = {"id": 1, "fullName": "A Player", "firstName": "A", "lastName": "Player"}
    assert loader.privacy_hits(row("mlb", "players", {"people": [person]}), ACCOUNTS) == []

    def hits(source: str, endpoint: str, payload: object) -> list[str]:
        return loader.privacy_hits(row(source, endpoint, payload), ACCOUNTS)

    nested = {"people": [{"id": 1, "currentTeam": {"firstName": "A"}}]}
    assert hits("mlb", "players", nested) == [
        "mlb/players k=1: key firstName at $.people[0].currentTeam"
    ]
    assert hits("mlb", "players", {"firstName": "A", "people": []}) == [
        "mlb/players k=1: key firstName at $"
    ]
    assert hits("mlb", "players", {"people": [{"displayName": "A"}]}) == [
        "mlb/players k=1: key displayName at $.people[0]"
    ]
    assert hits("mlb", "players", {"people": [{"owners": ["x"]}]}) == [
        "mlb/players k=1: key owners at $.people[0]"
    ]
    assert hits("mlb", "schedule", {"people": [person]}) == [
        "mlb/schedule k=1: key firstName at $.people[0]",
        "mlb/schedule k=1: key lastName at $.people[0]",
    ]
    assert len(hits("espn", "players", {"people": [person]})) == 2
    assert len(hits("mlb", "players", {"people": {"x": person}})) == 2
    # ESPN's ballplayer object is exempt in an ESPN row only (pre-PR review F1)
    in_espns_shape = {"people": [{"playerPoolEntry": {"player": {"firstName": "A"}}}]}
    assert hits("mlb", "players", in_espns_shape) == [
        "mlb/players k=1: key firstName at $.people[0].playerPoolEntry.player"
    ]


def test_a_guid_is_allowed_only_at_a_transactions_two_id_paths() -> None:
    """Catches the GUID exemption by name only, or by endpoint only: a GUID passes at
    `$.topics[i].id` and `$.topics[i].messages[j].id` of an `espn/transactions` payload and
    stops the upload at a third path of the same row (`topicId`, a nested `id`), in the
    partitions, the request path, key and file path, in another ESPN endpoint at the same
    path, as a key, and with text around it. No hit prints the value (R2.2, R2.6)."""
    topic, message = BARE_ACCOUNT.replace("272e", "5b1c"), BARE_ACCOUNT.replace("272e", "0e9d")
    ok = {"topics": [{"id": topic, "messages": [{"id": message}, {"id": message}]}]}
    assert loader.privacy_hits(row("espn", "transactions", ok), ACCOUNTS) == []

    def hits(payload: object, **overrides: str) -> list[str]:
        found = loader.privacy_hits(row("espn", "transactions", payload, **overrides), ACCOUNTS)
        assert BARE_ACCOUNT not in "".join(found).lower() and topic not in "".join(found)
        return found

    assert hits({"topics": [{"id": "t", "topicId": topic, "messages": []}]}) == [
        "espn/transactions k=1: GUID at $.topics[0].topicId"
    ]
    third = {"topics": [{"id": "t", "messages": [{"id": "m", "topicId": topic}]}]}
    assert hits(third) == ["espn/transactions k=1: GUID at $.topics[0].messages[0].topicId"]
    deeper = {"topics": [{"id": "t", "messages": [{"id": "m", "creationInfo": {"id": topic}}]}]}
    assert hits(deeper) == [
        "espn/transactions k=1: GUID at $.topics[0].messages[0].creationInfo.id"
    ]
    assert hits({"topics": [{"id": "t", "messages": [{"messages": [{"id": topic}]}]}]}) == [
        "espn/transactions k=1: GUID at $.topics[0].messages[0].messages[0].id"
    ]
    assert hits({"id": topic, "topics": []}) == ["espn/transactions k=1: GUID at $.id"]
    assert hits({"topics": [{"id": f"x {topic}", "messages": []}]}) == [
        "espn/transactions k=1: GUID at $.topics[0].id"
    ]
    assert hits({"topics": [{"id": f"{topic} {message}", "messages": []}]}) == [
        "espn/transactions k=1: GUID at $.topics[0].id"
    ]
    assert hits({"topics": [{"id": "t", "messages": [], topic: 1}]}) == [
        "espn/transactions k=1: GUID in a key at $.topics[0]"
    ]
    assert hits(ok, partitions=json.dumps({"x": topic})) == [
        "espn/transactions k=1: GUID at partitions $.x"
    ]
    for name in ("request_path", "request_key", "file_path"):
        assert hits(ok, **{name: f"/{topic}"}) == [f"espn/transactions: GUID in {name}"]
    # the same payload in another ESPN endpoint is not exempt
    for endpoint in ("teams", "roster", "matchup_days"):
        found = loader.privacy_hits(row("espn", endpoint, ok), ACCOUNTS)
        assert found[0] == f"espn/{endpoint} k=1: GUID at $.topics[0].id"
        assert len(found) == 3


def test_an_id_equal_to_a_known_account_stops_the_upload() -> None:
    """Catches a cross-check that compares text as written: the account is known braced and
    upper case, the id is bare lower case (and braced, mixed case or half-braced, which the
    GUID pattern also reads), and each equal id at either path stops the upload. A hit names
    the path and not the value (R2.3, R2.6)."""
    accounts = frozenset({BARE_ACCOUNT})
    for written in (BARE_ACCOUNT, GUID, GUID.lower(), BARE_ACCOUNT.upper(), "{" + BARE_ACCOUNT):
        topic = transactions_row(written)
        assert loader.privacy_hits(topic, accounts) == [
            "espn/transactions k=1: transaction id equals an account id at $.topics[0].id"
        ]
        message = transactions_row("t-1", written)
        assert loader.privacy_hits(message, accounts) == [
            "espn/transactions k=1: transaction id equals an account id at "
            "$.topics[0].messages[0].id"
        ]
        with pytest.raises(loader.PrivacyHit) as raised:
            loader.check([topic, message], accounts)
        assert len(raised.value.hits) == 2
        assert BARE_ACCOUNT not in "".join(raised.value.hits).lower()
    other = transactions_row(OTHER_GUID.strip("{}").lower(), "5b1c0f3e-0a8e-4d2c-9e57-0c5f6a1b2d3e")
    assert loader.check([other], accounts) == {("espn", "transactions"): 1}


def test_transaction_rows_with_no_known_accounts_stop_the_upload() -> None:
    """Catches a cross-check that silently checks nothing: with transaction rows to upload
    and no account id found, the upload stops with one hit, however many rows there are and
    however clean they look. With no transaction row to upload, an empty set is no reason
    to stop (R2.4)."""
    rows = [transactions_row("t-1"), transactions_row("t-2", request_key="k=2")]
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.check(rows, frozenset())
    assert raised.value.hits == [
        "espn/transactions: 2 row(s), and no account ids were found to check their ids against"
    ]
    assert loader.check(rows, ACCOUNTS) == {("espn", "transactions"): 2}
    settings = row("espn", "settings", {"n": 1})
    assert loader.check([settings], frozenset()) == {("espn", "settings"): 1}


def test_known_accounts_are_read_from_raw_teams_and_transactions(tmp_path: Path) -> None:
    """Catches accounts gathered from the projected rows, which hold none, from a path the
    spec does not list (`members[].notificationSettings[].id`, a topic's own id), from an
    author that is not one GUID whole, or from another endpoint; and ids kept as written
    when they are compared in their normal form (R2.3)."""
    teams = {
        "members": [
            {"id": GUID, "notificationSettings": [{"id": OTHER_GUID.replace("A1B2", "FFFF")}]},
            {"id": "not a guid"},
        ],
        "teams": [
            {
                "id": 1,
                "owners": [OTHER_GUID, "text"],
                "primaryOwner": "{abcdef01-0000-4000-8000-000000000001}",
            },
            {"id": 2, "owners": "not a list"},
        ],
    }
    transactions = {
        "topics": [
            {
                "id": "5b1c0f3e-0a8e-4d2c-9e57-0c5f6a1b2d3e",
                "author": "{ABCDEF01-0000-4000-8000-000000000002}",
                "messages": [
                    {"author": "{ABCDEF01-0000-4000-8000-000000000003}"},
                    {"author": "SOME_STRING"},
                    {"author": f"x {GUID}"},
                    {"author": 5},
                ],
            },
            {"author": "abcdef01-0000-4000-8000-000000000004"},
        ]
    }
    db, root = _landing(
        tmp_path,
        [
            ("espn", "teams", "k1", teams),
            ("espn", "transactions", "k2", transactions),
            (
                "espn",
                "settings",
                "k3",
                {"members": [{"id": "{ABCDEF01-0000-4000-8000-0000000000FF}"}]},
            ),
        ],
    )
    accounts = loader.known_accounts(loader.read_rows(db, root))
    assert accounts == {
        BARE_ACCOUNT,
        "a1b2c3d4-0000-4000-8000-0123456789ab",
        "abcdef01-0000-4000-8000-000000000001",
        "abcdef01-0000-4000-8000-000000000002",
        "abcdef01-0000-4000-8000-000000000003",
        "abcdef01-0000-4000-8000-000000000004",
    }
    assert isinstance(accounts, frozenset)
    (tmp_path / "none").mkdir()
    assert loader.known_accounts(loader.read_rows(*_landing(tmp_path / "none", []))) == frozenset()


def test_the_manifest_is_read_once_and_everything_is_drawn_from_that_snapshot(
    tmp_path: Path,
) -> None:
    """Catches a second query of the manifest per pass (design review F2): a capture loaded
    after the rows were read is not in a later pass, and is not among the known accounts.
    A manifest that disagrees with the landing zone stops the reading at construction, not
    at the first pass (R2.7)."""
    db, root = _landing(
        tmp_path,
        [
            ("espn", "settings", "k1", {"n": 1}),
            ("espn", "transactions", "k2", {"topics": [{"author": GUID}]}),
        ],
    )
    rows = loader.read_rows(db, root)
    before = [(r.key, r.payload) for r in rows]
    _load_late(db, root, "espn", "settings", {"n": 2}, "20270101T000000Z")
    _load_late(
        db, root, "espn", "transactions", {"topics": [{"author": OTHER_GUID}]}, "20270101T000001Z"
    )
    assert [(r.key, r.payload) for r in rows] == before
    assert loader.known_accounts(rows) == ACCOUNTS
    assert len(list(loader.read_rows(db, root))) == len(before) + 2

    other_db, other_root = _landing(tmp_path / "other", [("espn", "settings", "k1", {"n": 1})])
    shutil.rmtree(next(other_root.glob("espn/settings/*/*")))
    with pytest.raises(loader.ManifestDisagrees):
        loader.read_rows(other_db, other_root)


def test_the_manifest_is_read_in_one_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Catches the snapshot being one query per endpoint (pre-PR review F2): a load between
    the teams query and the transactions query would list a transaction whose account the
    known accounts never saw. Every endpoint's rows come from one connection and one query."""
    db, root = _member_landing(tmp_path)
    connections: list[object] = []
    real_connect = duckdb.connect

    def counting_connect(*args: object, **kwargs: object) -> object:
        con = real_connect(*args, **kwargs)  # type: ignore[arg-type]
        connections.append(con)
        return con

    monkeypatch.setattr(loader.duckdb, "connect", counting_connect)
    rows = loader.read_rows(db, root)
    assert len(connections) == 1
    assert {(c.source, c.endpoint) for c in rows.captures} == {
        ("espn", "teams"),
        ("espn", "transactions"),
        ("espn", "matchup_days"),
        ("espn", "settings"),
        ("mlb", "players"),
    }


def _load_late(
    db: Path, root: Path, source: str, endpoint: str, payload: object, stamp: str
) -> None:
    """A capture that lands, and is loaded into the manifest, after the rows were read."""
    zone = LandingZone(root)
    zone.write(
        source=source,
        endpoint=endpoint,
        partitions={"season": 2025},
        name=f"fetched_at={stamp}",
        payload=payload,  # type: ignore[arg-type]
        request={"url": f"https://x.test/{stamp}", "params": {"k": stamp}},
        fetched_at=stamp,
    )
    con = duckdb.connect(str(db))
    load_landing_zone(con, zone)
    con.close()


def test_a_capture_loaded_after_the_check_is_not_exported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches an unchecked row reaching the export: a capture that carries an account id
    and is loaded between the check and the write is not in the files, because the export
    writes the rows the check read (R2.7)."""
    db, root = _landing(tmp_path, [("espn", "settings", "k1", {"n": 1})])
    real_check = loader.check

    def check_then_load_late(rows: object, accounts: frozenset[str]) -> object:
        counts = real_check(rows, accounts)  # type: ignore[arg-type]
        _load_late(db, root, "espn", "settings", {"note": GUID}, "20270101T000000Z")
        return counts

    monkeypatch.setattr(loader, "check", check_then_load_late)
    files = loader.export(loader.read_rows(db, root), tmp_path / "out", ACCOUNTS)
    lines = [json.loads(line) for line in files[0].read_text().splitlines()]
    assert [line["payload"] for line in lines] == [{"n": 1}]
    assert GUID not in files[0].read_text()


def _dry_run(tmp_path: Path, captures: list[tuple[str, str, str, object]]) -> int:
    """The exit code of a dry run of the loader on a small landing root; it writes nothing."""
    db, root = _landing(tmp_path, captures)
    out = tmp_path / "out"
    code = loader.main(
        ["--db", str(db), "--raw-root", str(root), "--dry-run", "--export-dir", str(out)]
    )
    assert not out.exists()
    return code


def test_a_dry_run_says_how_many_accounts_and_exempt_ids_it_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Catches a dry run that reports rows and no privacy hit but does not say that the
    cross-check had accounts to check against, or how many ids it checked (Expected values:
    17 accounts, 34,882 ids on the real season)."""
    teams = {"members": [{"id": GUID}, {"id": OTHER_GUID}], "teams": []}
    transactions = {
        "topics": [
            {
                "id": "5b1c0f3e-0a8e-4d2c-9e57-0c5f6a1b2d3e",
                "messages": [{"id": "0e9d8c7b-6a5f-4e3d-8c2b-1a0f9e8d7c6b"}, {"id": "m-2"}],
            }
        ]
    }
    code = _dry_run(
        tmp_path, [("espn", "teams", "k1", teams), ("espn", "transactions", "k2", transactions)]
    )
    shown = capsys.readouterr().out
    assert code == 0
    assert "known account ids: 2" in shown
    assert "exempt transaction ids checked: 2" in shown
    assert "espn/transactions: 1 rows" in shown


def test_a_dry_run_stops_on_a_transaction_id_that_equals_an_account(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Catches the cross-check being wired into `check` but not into the run: a transaction
    whose topic id is a member's account id stops a dry run, exit 1, naming the path and
    not the id (R2.3, R2.6)."""
    teams = {"members": [{"id": GUID}], "teams": []}
    transactions = {"topics": [{"id": BARE_ACCOUNT, "messages": []}]}
    code = _dry_run(
        tmp_path, [("espn", "teams", "k1", teams), ("espn", "transactions", "k2", transactions)]
    )
    shown = capsys.readouterr().out
    assert code == 1
    assert "transaction id equals an account id at $.topics[0].id" in shown
    assert BARE_ACCOUNT not in shown.lower()
    assert "Nothing was written or uploaded." in shown


# -- the projection written as a landing root (R4.1, R4.3) -------------------------------------


def _ignored_root(tmp_path: Path) -> Path:
    """A scratch git repository that ignores `/ignored/`, and a root under it that does not
    exist yet. `visible/` beside it is not ignored."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("/ignored/\n")
    return repo


def _member_landing(tmp_path: Path) -> tuple[Path, Path]:
    """A small real-looking landing root: a teams capture whose members are the known
    accounts, a transactions capture, a matchup day and a settings capture."""
    return _landing(
        tmp_path,
        [
            ("espn", "teams", "k1", {**TEAMS, "members": [{"id": GUID}]}),
            ("espn", "transactions", "k2", TRANSACTIONS),
            ("espn", "matchup_days", "scoringPeriodId=12", MATCHUP_DAY),
            ("espn", "settings", "k4", {"n": 1}),
            ("mlb", "players", "k5", {"people": [{"id": 1, "firstName": "A"}]}),
        ],
    )


def _run(db: Path, root: Path, *extra: str) -> int:
    return loader.main(["--db", str(db), "--raw-root", str(root), "--dry-run", *extra])


def test_the_landing_root_written_holds_the_projected_captures_under_their_own_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Catches a capture written under a new stamp, partitions or request, which would change
    the capture `fo_espn_latest` picks and so what the staging models return; a whole payload
    written in place of the projection; and an endpoint written that is not a projected one
    (R4.1)."""
    repo = _ignored_root(tmp_path)
    db, root = _member_landing(tmp_path / "src")
    target = repo / "ignored" / "proj"
    assert _run(db, root, "--write-landing", str(target)) == 0
    assert "wrote 3 captures" in capsys.readouterr().out

    written = {(c.meta["source"], c.meta["endpoint"]): c for c in LandingZone(target).iter_landed()}
    assert sorted(written) == [
        ("espn", "matchup_days"),
        ("espn", "teams"),
        ("espn", "transactions"),
    ]
    projected = {
        ("espn", "matchup_days"): loader.project_matchup_day(MATCHUP_DAY),
        ("espn", "teams"): PROJECTED_TEAMS,
        ("espn", "transactions"): PROJECTED_TRANSACTIONS,
    }
    for original in LandingZone(root).iter_landed():
        pair = (original.meta["source"], original.meta["endpoint"])
        if pair not in projected:
            continue
        copy = written[pair]
        assert copy.payload == projected[pair]
        assert copy.path.relative_to(target) == original.path.relative_to(root)
        for name in ("partitions", "url", "params", "request_key", "fetched_at"):
            assert copy.meta[name] == original.meta[name], name
    # the manifest of the written root names the same keys as the source's
    out = duckdb.connect(str(tmp_path / "proj.duckdb"))
    load_landing_zone(out, LandingZone(target))
    src = duckdb.connect(str(db), read_only=True)
    columns = "source, endpoint, request_path, request_key, fetched_at, file_path, partitions"
    query = (
        f"select {columns} from raw.captures where endpoint in ({', '.join('?' * 3)}) order by all"
    )
    pairs = [e for _, e in sorted(projected)]
    assert out.execute(query, pairs).fetchall() == src.execute(query, pairs).fetchall()


def test_nothing_is_written_to_the_landing_root_when_the_check_stops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Catches captures written before, or in spite of, a privacy hit: a transaction whose id
    is an account id stops the upload, and the root must not exist afterwards (R4.1)."""
    repo = _ignored_root(tmp_path)
    teams = {"members": [{"id": GUID}], "teams": []}
    transactions = {"topics": [{"id": BARE_ACCOUNT, "messages": []}]}
    db, root = _landing(
        tmp_path / "src",
        [("espn", "teams", "k1", teams), ("espn", "transactions", "k2", transactions)],
    )
    target = repo / "ignored" / "proj"
    assert _run(db, root, "--write-landing", str(target)) == 1
    assert "Nothing was written or uploaded." in capsys.readouterr().out
    assert not target.exists() and not (repo / "ignored").exists()


def test_a_landing_root_git_does_not_ignore_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Catches real captures written where a commit could take them: a root that git does not
    ignore (in a repository, outside any, or one that already exists) is refused, nothing is
    written there, and the run says why (R4.3, R4.1)."""
    repo = _ignored_root(tmp_path)
    db, root = _member_landing(tmp_path / "src")
    existing = repo / "ignored" / "old"
    existing.mkdir(parents=True)
    (existing / "keep.txt").write_text("x")
    for target in (repo / "visible" / "proj", tmp_path / "outside" / "proj", existing):
        assert _run(db, root, "--write-landing", str(target)) == 1, target
        shown = capsys.readouterr().out
        assert "landing root" in shown and "refused" in shown, shown
        assert "wrote" not in shown
    assert not (repo / "visible").exists() and not (tmp_path / "outside").exists()
    assert sorted(p.name for p in existing.iterdir()) == ["keep.txt"]
    with pytest.raises(loader.LandingRootRefused):
        loader.write_landing(loader.read_rows(db, root), repo / "visible" / "proj")
    assert not (repo / "visible").exists()
