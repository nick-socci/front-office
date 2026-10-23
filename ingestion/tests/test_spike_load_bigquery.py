"""The spike's loader: what may leave the machine, and whether it arrived whole (spec 0130,
R3; ADR 0054).

Nothing here talks to BigQuery. The privacy check and the row comparison are pure
functions over rows; the reading of the manifest and the landing zone is tested on a small
landing root and DuckDB file.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb
import pytest

import spike_load_bigquery as loader
from front_office.landing import LandingZone
from front_office.load import load_landing_zone

GUID = "{272E019C-48D5-42F3-B289-C48A1B163E19}"


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
    hits = loader.privacy_hits(row("espn", "roster", {"teams": [{"note": f"by {GUID}"}]}))
    assert hits == ["espn/roster k=1: GUID at $.teams[0].note"]
    assert GUID not in "".join(hits)


def test_a_guid_as_a_key_or_outside_the_payload_is_found_too() -> None:
    """Catches a GUID that is a key of an object, or in the partitions, slipping through a
    check that reads only values of the payload."""
    as_key = loader.privacy_hits(row("espn", "settings", {"byOwner": {GUID: 1}}))
    assert as_key == ["espn/settings k=1: GUID in a key at $.byOwner"]
    in_partitions = loader.privacy_hits(
        row("espn", "settings", {}, partitions=json.dumps({"owner": GUID}))
    )
    assert in_partitions == ["espn/settings k=1: GUID at partitions $.owner"]


def test_a_guid_in_the_request_key_is_not_printed_by_any_message_about_the_row() -> None:
    """Catches the row's label carrying a value: a row keyed by an account id that is
    rejected for something else would print the id in every message about it (PR #142,
    review round 1)."""
    keyed = row("espn", "roster", {"members": []}, request_key=f"owner={GUID}&view=mRoster")
    hits = loader.privacy_hits(keyed)
    assert hits, "the row should be rejected"
    assert GUID not in "".join(hits)
    assert any("owner=<guid>&view=mRoster" in hit for hit in hits)
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.check([keyed])
    assert GUID not in "".join(raised.value.hits) + str(raised.value)


def test_a_guid_that_is_a_key_on_the_way_to_a_hit_is_not_printed_in_the_path() -> None:
    """Catches a path carrying a value: a path is made of the document's keys, so a hit
    found under an object keyed by account id would print the id (PR #142, review round
    2)."""
    nested = row("espn", "settings", {"byOwner": {GUID: {"members": [], "note": f"x {GUID}"}}})
    hits = loader.privacy_hits(nested)
    assert len(hits) >= 3, hits
    assert GUID not in "".join(hits)
    assert any("$.byOwner.<guid>" in hit for hit in hits)


def test_mlbs_game_guid_is_allowed() -> None:
    """Catches the GUID rule reaching MLB rows, where gameGuid is a public game id and every
    schedule row would be refused."""
    schedule = {"dates": [{"games": [{"gameGuid": "272e019c-48d5-42f3-b289-c48a1b163e19"}]}]}
    assert loader.privacy_hits(row("mlb", "schedule", schedule)) == []


def test_a_members_name_stops_the_upload() -> None:
    """Catches a league member's name going up: a forbidden key is a hit in any row."""
    payload = {"members": [{"firstName": "A", "lastName": "B"}]}
    assert loader.privacy_hits(row("espn", "settings", payload)) == [
        "espn/settings k=1: key members at $",
        "espn/settings k=1: key firstName at $.members[0]",
        "espn/settings k=1: key lastName at $.members[0]",
    ]
    assert loader.privacy_hits(row("mlb", "schedule", {"displayName": "x"})) == [
        "mlb/schedule k=1: key displayName at $"
    ]


def test_a_ballplayers_own_name_is_allowed_and_nothing_else_in_that_object() -> None:
    """Catches the one exception widening: firstName and lastName directly in a
    playerPoolEntry.player object name a ballplayer; an owner there, or a name one level
    further in, does not."""
    player = {"firstName": "Shohei", "lastName": "Ohtani", "id": 39832}
    entry = {"teams": [{"roster": {"entries": [{"playerPoolEntry": {"player": player}}]}}]}
    assert loader.privacy_hits(row("espn", "roster", entry)) == []

    player_with_owner = {**player, "owners": ["x"]}
    entry = {"playerPoolEntry": {"player": player_with_owner}}
    assert loader.privacy_hits(row("espn", "roster", entry)) == [
        "espn/roster k=1: key owners at $.playerPoolEntry.player"
    ]
    deeper = {"playerPoolEntry": {"player": {"agent": {"firstName": "A"}}}}
    assert loader.privacy_hits(row("espn", "roster", deeper)) == [
        "espn/roster k=1: key firstName at $.playerPoolEntry.player.agent"
    ]
    elsewhere = {"player": {"firstName": "A"}}
    assert loader.privacy_hits(row("espn", "roster", elsewhere)) == [
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
        loader.check([row("espn", "draft", {"teams": []})])
    assert any("not on the allowlist" in hit for hit in raised.value.hits)
    assert loader.check([row("espn", "settings", {"teams": []})]) == {("espn", "settings"): 1}


def test_a_hit_anywhere_means_nothing_is_written(tmp_path: Path) -> None:
    """Catches files being exported for the clean endpoints before a hit in another is
    found: on any hit nothing is written at all."""
    clean = row("mlb", "schedule", {"dates": []})
    dirty = row("espn", "settings", {"members": []}, request_key="k=2")
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.export([clean, dirty], tmp_path / "out")
    assert raised.value.hits == ["espn/settings k=2: key members at $"]
    assert not (tmp_path / "out").exists()


def test_the_export_is_one_file_per_endpoint_with_json_as_json(tmp_path: Path) -> None:
    """Catches a payload written as a quoted string, which would load as a JSON string and
    not an object, or two endpoints sharing a file."""
    rows = [
        row("mlb", "schedule", {"dates": [1.5]}),
        row("espn", "settings", {"id": 7}, request_key="k=2", partitions='{"season": 2026}'),
    ]
    files = loader.export(rows, tmp_path / "out")
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
    assert loader.privacy_hits(row("espn", "matchup_days", json.loads(text))) == []


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
        loader.check(loader.read_rows(db, root))
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
        loader.check(loader.read_rows(db, root))
    assert "committed, not in raw.captures: espn/settings/" in str(raised.value)


def test_a_row_of_a_projected_endpoint_that_was_not_projected_stops_the_upload() -> None:
    """Catches a caller handing the check a whole capture of one of the two endpoints, even
    one with nothing the privacy patterns know: only the projection may go up."""
    whole = row("espn", "matchup_days", {"id": 1, "schedule": [], "status": {"x": 1}})
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.check([whole])
    assert raised.value.hits == ["espn/matchup_days k=1: not in its projected form (ADR 0061)"]
    projected = row("espn", "matchup_days", loader.project_matchup_day(MATCHUP_DAY))
    assert loader.check([projected]) == {("espn", "matchup_days"): 1}


def test_a_whole_teams_or_transactions_capture_is_refused() -> None:
    """Catches a raw capture of `espn/teams` or `espn/transactions` reaching the export when
    a caller builds its own rows: a whole capture is refused as not in its projected form
    (R2.5), not only by the key and GUID patterns. A teams row is refused for that reason
    and not for being off the allowlist."""
    for endpoint, whole in (("teams", TEAMS), ("transactions", TRANSACTIONS)):
        with pytest.raises(loader.PrivacyHit) as raised:
            loader.check([row("espn", endpoint, whole)])
        assert any("not in its projected form" in hit for hit in raised.value.hits)
        assert not any("allowlist" in hit for hit in raised.value.hits)
        assert GUID not in "".join(raised.value.hits)
    # nothing the privacy patterns know, and still refused
    clean = {"id": 1, "teams": [{"id": 1, "logo": "x"}]}
    with pytest.raises(loader.PrivacyHit) as raised:
        loader.check([row("espn", "teams", clean)])
    assert raised.value.hits == ["espn/teams k=1: not in its projected form (ADR 0061)"]


def test_a_guid_left_in_a_projected_row_still_stops_the_upload() -> None:
    """Catches the projection being trusted in place of the check: an account id in the
    request key of a projected row is found like any other."""
    dirty = row("espn", "transactions", {}, request_key=f"owner={GUID}")
    with pytest.raises(loader.PrivacyHit):
        loader.check([dirty])
