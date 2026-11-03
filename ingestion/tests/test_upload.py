"""What may leave the machine for BigQuery (spec 0140, R6; ADRs 0054, 0061, 0093 to 0095).

Pure functions over parsed JSON: the privacy check, the three projections and the account ids.
Nothing here reads a landing zone, a warehouse or BigQuery.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import make_fixtures
from front_office import privacy, upload

GUID = "{272E019C-48D5-42F3-B289-C48A1B163E19}"
# Another account id, and the normal form (braces stripped, lower case) of both: the form in
# which the check keeps the known accounts.
OTHER_GUID = "{A1B2C3D4-0000-4000-8000-0123456789AB}"
ACCOUNTS = frozenset({"272e019c-48d5-42f3-b289-c48a1b163e19"})


def row(source: str, endpoint: str, payload: object, **overrides: Any) -> upload.Row:
    values: dict[str, Any] = {
        "source": source,
        "endpoint": endpoint,
        "request_path": "/a/path",
        "request_key": "k=1",
        "fetched_at": "20260926T162307Z",
        "file_path": f"data/raw/{source}/{endpoint}/payload.json",
        "partitions": {},
        "document": payload,
    }
    values.update(overrides)
    return upload.Row(**values)


def test_the_fixtures_and_the_upload_share_one_list_of_wanted_fields() -> None:
    """Catches the fixtures and the upload drifting to two lists: a field the fixtures carry
    that the upload drops (or the reverse) would pass CI and fail on the real season (ADR
    0093)."""
    assert make_fixtures.ESPN_TEAM_FIELDS is upload.ESPN_TEAM_FIELDS
    assert make_fixtures.ESPN_TRANSACTION_MESSAGE_FIELDS is upload.ESPN_TRANSACTION_MESSAGE_FIELDS


# -- the privacy check (R3.3) ------------------------------------------------------------


def test_a_guid_in_an_espn_row_stops_the_upload_and_the_value_is_not_reported() -> None:
    """Catches an ESPN account id going up, and the check printing the id it found."""
    hits = upload.privacy_hits(row("espn", "roster", {"teams": [{"note": f"by {GUID}"}]}), ACCOUNTS)
    assert hits == ["espn/roster k=1: GUID at $.teams[0].note"]
    assert GUID not in "".join(hits)


def test_a_guid_as_a_key_or_outside_the_payload_is_found_too() -> None:
    """Catches a GUID that is a key of an object, or in the partitions, slipping through a
    check that reads only values of the payload."""
    as_key = upload.privacy_hits(row("espn", "settings", {"byOwner": {GUID: 1}}), ACCOUNTS)
    assert as_key == ["espn/settings k=1: GUID in a key at $.byOwner"]
    in_partitions = upload.privacy_hits(
        row("espn", "settings", {}, partitions={"owner": GUID}), ACCOUNTS
    )
    assert in_partitions == ["espn/settings k=1: GUID at partitions $.owner"]


def test_a_guid_in_the_request_key_is_not_printed_by_any_message_about_the_row() -> None:
    """Catches the row's label carrying a value: a row keyed by an account id that is
    rejected for something else would print the id in every message about it (PR #142,
    review round 1)."""
    keyed = row("espn", "roster", {"members": []}, request_key=f"owner={GUID}&view=mRoster")
    hits = upload.privacy_hits(keyed, ACCOUNTS)
    assert hits, "the row should be rejected"
    assert GUID not in "".join(hits)
    assert any("owner=<guid>&view=mRoster" in hit for hit in hits)
    with pytest.raises(upload.PrivacyHit) as raised:
        upload.check([keyed], ACCOUNTS)
    assert GUID not in "".join(raised.value.hits) + str(raised.value)


def test_a_guid_that_is_a_key_on_the_way_to_a_hit_is_not_printed_in_the_path() -> None:
    """Catches a path carrying a value: a path is made of the document's keys, so a hit
    found under an object keyed by account id would print the id (PR #142, review round
    2)."""
    nested = row("espn", "settings", {"byOwner": {GUID: {"members": [], "note": f"x {GUID}"}}})
    hits = upload.privacy_hits(nested, ACCOUNTS)
    assert len(hits) >= 3, hits
    assert GUID not in "".join(hits)
    assert any("$.byOwner.<guid>" in hit for hit in hits)


def test_mlbs_game_guid_is_allowed() -> None:
    """Catches the GUID rule reaching MLB rows, where gameGuid is a public game id and every
    schedule row would be refused."""
    schedule = {"dates": [{"games": [{"gameGuid": "272e019c-48d5-42f3-b289-c48a1b163e19"}]}]}
    assert upload.privacy_hits(row("mlb", "schedule", schedule), ACCOUNTS) == []


def test_a_members_name_stops_the_upload() -> None:
    """Catches a league member's name going up: a forbidden key is a hit in any row."""
    payload = {"members": [{"firstName": "A", "lastName": "B"}]}
    assert upload.privacy_hits(row("espn", "settings", payload), ACCOUNTS) == [
        "espn/settings k=1: key members at $",
        "espn/settings k=1: key firstName at $.members[0]",
        "espn/settings k=1: key lastName at $.members[0]",
    ]
    assert upload.privacy_hits(row("mlb", "schedule", {"displayName": "x"}), ACCOUNTS) == [
        "mlb/schedule k=1: key displayName at $"
    ]


def test_a_ballplayers_own_name_is_allowed_and_nothing_else_in_that_object() -> None:
    """Catches the one exception widening: firstName and lastName directly in a
    playerPoolEntry.player object name a ballplayer; an owner there, or a name one level
    further in, does not."""
    player = {"firstName": "Shohei", "lastName": "Ohtani", "id": 39832}
    entry = {"teams": [{"roster": {"entries": [{"playerPoolEntry": {"player": player}}]}}]}
    assert upload.privacy_hits(row("espn", "roster", entry), ACCOUNTS) == []

    player_with_owner = {**player, "owners": ["x"]}
    entry = {"playerPoolEntry": {"player": player_with_owner}}
    assert upload.privacy_hits(row("espn", "roster", entry), ACCOUNTS) == [
        "espn/roster k=1: key owners at $.playerPoolEntry.player"
    ]
    deeper = {"playerPoolEntry": {"player": {"agent": {"firstName": "A"}}}}
    assert upload.privacy_hits(row("espn", "roster", deeper), ACCOUNTS) == [
        "espn/roster k=1: key firstName at $.playerPoolEntry.player.agent"
    ]
    elsewhere = {"player": {"firstName": "A"}}
    assert upload.privacy_hits(row("espn", "roster", elsewhere), ACCOUNTS) == [
        "espn/roster k=1: key firstName at $.player"
    ]


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


def test_only_the_listed_endpoints_are_uploaded() -> None:
    """Catches an endpoint being added that no ADR allows, and one of the eleven (ADRs 0054,
    0061, 0093, 0095) being left out, in particular `mlb/players`. (The reading of the
    manifest, which the spike's version of this test also held, is the run's.)"""
    assert set(upload.UPLOADED) == LISTED
    assert len(upload.UPLOADED) == 11
    assert set(upload.ALLOWLIST) == LISTED - {
        ("espn", "teams"),
        ("espn", "transactions"),
        ("espn", "matchup_days"),
    }
    assert set(upload.PROJECTIONS) == {
        ("espn", "teams"),
        ("espn", "transactions"),
        ("espn", "matchup_days"),
    }


def test_a_row_off_the_allowlist_stops_the_upload_however_clean_it_is() -> None:
    """Catches the second guard going: the check refuses any row it is handed that is not on
    the list, so a caller that builds its own rows cannot upload `draft`."""
    with pytest.raises(upload.PrivacyHit) as raised:
        upload.check([row("espn", "draft", {"teams": []})], ACCOUNTS)
    assert any("not on the allowlist" in hit for hit in raised.value.hits)
    assert upload.check([row("espn", "settings", {"teams": []})], ACCOUNTS) == {
        ("espn", "settings"): 1
    }


# -- the endpoints uploaded as projections (ADR 0061) ------------------------------------------

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
    projected = upload.project_matchup_day(MATCHUP_DAY)
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
    text = json.dumps(upload.project_matchup_day(MATCHUP_DAY))
    keys = {key for _, key, _ in privacy.walk(json.loads(text))}
    assert not keys & privacy.FORBIDDEN_KEYS
    assert not keys & {"fullName", "lineupSlotId", "injuryStatus", "teams", "settings", "nested"}
    assert not privacy.GUID.search(text)
    assert upload.privacy_hits(row("espn", "matchup_days", json.loads(text)), ACCOUNTS) == []


def test_a_projection_is_built_from_wanted_fields_so_an_unknown_one_is_dropped() -> None:
    """Catches a projection made by removing known member keys: a key ESPN adds tomorrow
    must not go up because nobody listed it."""
    grown = {**MATCHUP_DAY, "newThing": {"author": GUID}}
    grown["schedule"] = [{**MATCHUP_DAY["schedule"][0], "alsoNew": GUID}]  # type: ignore[dict-item]
    projected = upload.project_matchup_day(grown)
    assert GUID not in json.dumps(projected) and "newThing" not in projected
    assert projected["schedule"] == [PROJECTED_FIRST_MATCHUP]


def test_a_payload_of_an_unexpected_shape_projects_to_what_it_can() -> None:
    """Catches the projection crashing, or passing a value through, when ESPN answers with
    something else: no schedule, a schedule that is not a list, a side that is not an
    object."""
    assert upload.project_matchup_day({"id": 1}) == {"id": 1, "schedule": []}
    assert upload.project_matchup_day({"schedule": "x"}) == {"schedule": []}
    assert upload.project_matchup_day({"schedule": [{"home": GUID}, GUID]}) == {
        "schedule": [{}, {}]
    }
    assert upload.project_matchup_day([GUID]) == {"schedule": []}


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
    `members`, `owners`, `primaryOwner`, a logo and a key nobody listed), and a wanted field
    being lost (ADR 0093, R1.4)."""
    projected = upload.project_teams(TEAMS)
    assert projected == PROJECTED_TEAMS
    text = json.dumps(projected)
    assert GUID not in text and "members" not in projected and "owners" not in text


def test_a_transaction_goes_up_as_its_ids_and_message_fields() -> None:
    """Catches `author`, `creationInfo`, `topicId` or an unlisted key going up from a
    transaction log, and a field staging reads (a topic's id and date, a message's id and
    the fixtures' ESPN_TRANSACTION_MESSAGE_FIELDS) being lost (ADR 0093, R1.3, R1.4)."""
    projected = upload.project_transactions(TRANSACTIONS)
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
    projected = upload.project_teams({"id": {"x": GUID}, "seasonId": [1], "teams": [team]})
    assert projected == {"teams": [{"id": 1, "record": {"overall": {"losses": 2}}}]}

    message = {"id": MESSAGE_ID, "to": {"author": GUID}, "from": [GUID], "for": None, "date": 5}
    topic = {"id": {"author": GUID}, "date": [1], "messages": [message]}
    assert upload.project_transactions({"topics": [topic]}) == {
        "topics": [{"messages": [{"id": MESSAGE_ID, "for": None, "date": 5}]}]
    }


def test_a_teams_or_transactions_payload_of_an_unexpected_shape_projects_to_what_it_can() -> None:
    """Catches the projection crashing, or passing a value through, when ESPN answers with
    something else: no teams, teams that are not a list, no topics, messages that are not a
    list, a payload that is not an object."""
    assert upload.project_teams({"id": 1}) == {"id": 1, "teams": []}
    assert upload.project_teams({"teams": GUID}) == {"teams": []}
    assert upload.project_teams([GUID]) == {"teams": []}
    assert upload.project_transactions({"topics": "x"}) == {"topics": []}
    assert upload.project_transactions([GUID]) == {"topics": []}
    assert upload.project_transactions({"topics": [{"id": TOPIC_ID, "messages": GUID}]}) == {
        "topics": [{"id": TOPIC_ID, "messages": []}]
    }


def test_a_whole_teams_or_transactions_capture_is_refused() -> None:
    """Catches a raw capture of `espn/teams` or `espn/transactions` reaching the upload when
    a caller builds its own rows: a whole capture is refused as not in its projected form
    (R2.5), not only by the key and GUID patterns. A teams row is refused for that reason
    and not for being off the allowlist."""
    for endpoint, whole in (("teams", TEAMS), ("transactions", TRANSACTIONS)):
        with pytest.raises(upload.PrivacyHit) as raised:
            upload.check([row("espn", endpoint, whole)], ACCOUNTS)
        assert any("not what its projection would produce" in hit for hit in raised.value.hits)
        assert not any("allowlist" in hit for hit in raised.value.hits)
        assert GUID not in "".join(raised.value.hits)
    # nothing the privacy patterns know, and still refused
    clean = {"id": 1, "teams": [{"id": 1, "logo": "x"}]}
    with pytest.raises(upload.PrivacyHit) as raised:
        upload.check([row("espn", "teams", clean)], ACCOUNTS)
    assert raised.value.hits == ["espn/teams k=1: not what its projection would produce"]


def test_a_projected_teams_or_transactions_row_passes_the_check() -> None:
    """Catches the projection rule refusing what the projection itself produced."""
    rows = [
        row("espn", "teams", upload.project_teams(TEAMS)),
        row("espn", "transactions", upload.project_transactions(TRANSACTIONS)),
    ]
    assert upload.check(rows, ACCOUNTS) == {("espn", "teams"): 1, ("espn", "transactions"): 1}


def test_a_matchup_days_document_is_not_held_to_its_projection_by_the_check() -> None:
    """Catches the "not what its projection would produce" rule being applied to
    `matchup_days`: its document is the projection reduced to a declared structure (the
    league id as text, a missing field as null), which the projection alone does not
    reproduce, so the check leaves that to where its row is built. The privacy patterns
    still apply to it."""
    reduced = {**upload.project_matchup_day(MATCHUP_DAY), "id": "73677", "seasonId": None}
    assert upload.check([row("espn", "matchup_days", reduced)], ACCOUNTS) == {
        ("espn", "matchup_days"): 1
    }
    with pytest.raises(upload.PrivacyHit):
        upload.check([row("espn", "matchup_days", {"members": []})], ACCOUNTS)


def test_a_guid_left_in_a_projected_row_still_stops_the_upload() -> None:
    """Catches the projection being trusted in place of the check: an account id in the
    request key of a projected row is found like any other."""
    dirty = row("espn", "transactions", {}, request_key=f"owner={GUID}")
    with pytest.raises(upload.PrivacyHit):
        upload.check([dirty], ACCOUNTS)


# -- the member-data endpoints: names in MLB's player list, transaction ids (ADRs 0094, 0095) --

BARE_ACCOUNT = "272e019c-48d5-42f3-b289-c48a1b163e19"  # the account of GUID, as ESPN's ids look


def transactions_row(topic_id: str, message_id: str = "m-1", **overrides: Any) -> upload.Row:
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
    assert upload.privacy_hits(row("mlb", "players", {"people": [person]}), ACCOUNTS) == []

    def hits(source: str, endpoint: str, payload: object) -> list[str]:
        return upload.privacy_hits(row(source, endpoint, payload), ACCOUNTS)

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
    assert upload.privacy_hits(row("espn", "transactions", ok), ACCOUNTS) == []

    def hits(payload: object, **overrides: Any) -> list[str]:
        found = upload.privacy_hits(row("espn", "transactions", payload, **overrides), ACCOUNTS)
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
    assert hits(ok, partitions={"x": topic}) == ["espn/transactions k=1: GUID at partitions $.x"]
    for name in ("request_path", "request_key", "file_path"):
        assert hits(ok, **{name: f"/{topic}"}) == [f"espn/transactions: GUID in {name}"]
    # the same payload in another ESPN endpoint is not exempt
    for endpoint in ("teams", "roster", "matchup_days"):
        found = upload.privacy_hits(row("espn", endpoint, ok), ACCOUNTS)
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
        assert upload.privacy_hits(topic, accounts) == [
            "espn/transactions k=1: transaction id equals an account id at $.topics[0].id"
        ]
        message = transactions_row("t-1", written)
        assert upload.privacy_hits(message, accounts) == [
            "espn/transactions k=1: transaction id equals an account id at "
            "$.topics[0].messages[0].id"
        ]
        with pytest.raises(upload.PrivacyHit) as raised:
            upload.check([topic, message], accounts)
        assert len(raised.value.hits) == 2
        assert BARE_ACCOUNT not in "".join(raised.value.hits).lower()
    other = transactions_row(OTHER_GUID.strip("{}").lower(), "5b1c0f3e-0a8e-4d2c-9e57-0c5f6a1b2d3e")
    assert upload.check([other], accounts) == {("espn", "transactions"): 1}


def test_transaction_rows_with_no_known_accounts_stop_the_upload() -> None:
    """Catches a cross-check that silently checks nothing: with transaction rows to upload
    and no account id found, the upload stops with one hit, however many rows there are and
    however clean they look. With no transaction row to upload, an empty set is no reason
    to stop (R2.4)."""
    rows = [transactions_row("t-1"), transactions_row("t-2", request_key="k=2")]
    with pytest.raises(upload.PrivacyHit) as raised:
        upload.check(rows, frozenset())
    assert raised.value.hits == [
        "espn/transactions k=1: no account ids were found to check the ids at $.topics",
        "espn/transactions k=2: no account ids were found to check the ids at $.topics",
    ]
    assert upload.check(rows, ACCOUNTS) == {("espn", "transactions"): 2}
    settings = row("espn", "settings", {"n": 1})
    assert upload.check([settings], frozenset()) == {("espn", "settings"): 1}


def test_account_ids_are_read_from_a_raw_teams_or_transactions_payload() -> None:
    """Catches accounts gathered from a path the spec does not list
    (`members[].notificationSettings[].id`, a topic's own id), from an author that is not one
    GUID whole, or from another endpoint; and ids kept as written when they are compared in
    their normal form (R2.3)."""
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
    assert upload.account_ids("espn", "teams", teams) == {
        BARE_ACCOUNT,
        "a1b2c3d4-0000-4000-8000-0123456789ab",
        "abcdef01-0000-4000-8000-000000000001",
    }
    found = upload.account_ids("espn", "transactions", transactions)
    assert found == {
        "abcdef01-0000-4000-8000-000000000002",
        "abcdef01-0000-4000-8000-000000000003",
        "abcdef01-0000-4000-8000-000000000004",
    }
    assert isinstance(found, frozenset)
    # another endpoint holds none that count, whatever its shape, and a payload of the wrong
    # shape holds none
    settings = {"members": [{"id": "{ABCDEF01-0000-4000-8000-0000000000FF}"}]}
    assert upload.account_ids("espn", "settings", settings) == frozenset()
    assert upload.account_ids("mlb", "teams", teams) == frozenset()
    assert upload.account_ids("espn", "teams", [GUID]) == frozenset()
    assert upload.account_ids("espn", "transactions", None) == frozenset()


def test_exempt_ids_checked_counts_whole_guids_at_the_two_id_paths() -> None:
    """Catches the count of exempt ids drifting from what the check exempts: only whole GUIDs
    at a transaction's topic and message id paths count, not a plain id, and no row of
    another endpoint does. (Expected values: 34,882 ids on the real season.)"""
    transactions = {
        "topics": [
            {
                "id": "5b1c0f3e-0a8e-4d2c-9e57-0c5f6a1b2d3e",
                "messages": [{"id": "0e9d8c7b-6a5f-4e3d-8c2b-1a0f9e8d7c6b"}, {"id": "m-2"}],
            }
        ]
    }
    assert upload.exempt_ids_checked(row("espn", "transactions", transactions)) == 2
    assert upload.exempt_ids_checked(row("espn", "teams", transactions)) == 0
