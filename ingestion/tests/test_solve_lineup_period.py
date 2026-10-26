"""Tests for the lineup solver's entry point, solve_lineup_period (spec 0137, ADRs 0103, 0104).

The entry point is what a BigQuery UDF and the DuckDB function both call with plain dicts,
so the cases are hand-built options and slots, as in test_lineup_solver.py. Slot 1 is a
hitter slot and slot 10 a pitcher slot, one of each.
"""

import ast
import random
from datetime import date
from pathlib import Path

import pytest

from solve_lineup_period import solve_lineup_period

SOURCE = Path(__file__).resolve().parents[2] / "dbt/functions/solve_lineup_period.py"
TEAM = "platform=espn, league_id=L, season=2026, fantasy_team_id=3"
DAY1, DAY2, DAY3 = date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)
SLOTS = [
    {"slot_id": 1, "role": "hitter", "count": 1},
    {"slot_id": 10, "role": "pitcher", "count": 1},
]


def option(day, player_id, value, *, slot_id=1, actual=False, start=False):
    role = "pitcher" if slot_id == 10 else "hitter"
    return {
        "scoring_date": day,
        "player_id": player_id,
        "slot_id": slot_id,
        "role": role,
        "value": value,
        "is_actual": actual,
        "is_start": start,
    }


def solve(options, *, period=1, slots=SLOTS, limit=None, team=TEAM):
    return solve_lineup_period(team, period, options, slots, limit)


def chosen(rows):
    return {(r["scoring_date"], r["player_id"]) for r in rows}


def test_values_a_float_apart_give_the_same_lineup():
    """Catches skipping round(value, 12): the last-digit noise between two players worth the
    same would decide who is chosen, and the two warehouses' noise differs (ADR 0104)."""
    noisy_first = [option(DAY1, 1, 5.0 + 1e-15), option(DAY1, 2, 5.0)]
    noisy_second = [option(DAY1, 1, 5.0), option(DAY1, 2, 5.0 + 1e-15)]
    assert solve(noisy_first) == solve(noisy_second)


def test_a_tie_made_by_rounding_is_broken_the_way_an_exact_tie_is():
    """Catches a tie that noise would break one way being broken that way after rounding:
    values equal to 12 places must give the lineup that exactly equal values give."""
    exact = solve([option(DAY1, 1, 5.0), option(DAY1, 2, 5.0)])
    for noise in (1e-15, -1e-15):
        assert solve([option(DAY1, 1, 5.0), option(DAY1, 2, 5.0 + noise)]) == exact
        assert solve([option(DAY1, 1, 5.0 + noise), option(DAY1, 2, 5.0)]) == exact


def test_a_difference_above_the_rounding_still_decides():
    """Catches rounding too coarsely: values 1e-6 apart are different values."""
    rows = solve([option(DAY1, 1, 5.0), option(DAY1, 2, 5.000001)])
    assert chosen(rows) == {(DAY1, 2)}


def test_any_null_value_gives_no_rows():
    """Catches solving a period with an unvalued option (spec 0164, R2.1): it has no rows on
    any of its days, including days whose options are all valued."""
    options = [option(DAY1, 1, 5.0), option(DAY2, 2, 3.0), option(DAY2, 3, None)]
    assert solve(options) == []


def test_a_value_beyond_the_bound_fails_even_in_an_unvalued_period():
    """Catches skipping the bound check when the period is skipped for a null: a non-null
    value out of bound on another day must still fail the build (R1.8, R2.3)."""
    options = [option(DAY1, 1, None), option(DAY2, 2, 5000.0)]
    with pytest.raises(ValueError, match="out of bound"):
        solve(options)


def test_the_bound_message_names_the_team_and_the_scoring_date():
    """Catches an error a UDF's caller cannot place: a UDF sees only its arguments, so the
    message must carry the team and the day itself (R2.3)."""
    options = [option(DAY1, 1, 5.0), option(DAY2, 2, -5000.0)]
    with pytest.raises(ValueError) as caught:
        solve(options)
    message = str(caught.value)
    assert message.startswith("optimal lineup failed for team-day " + TEAM)
    assert "scoring_date=2026-06-02" in message
    assert "player 2" in message


def test_the_bound_is_checked_on_the_rounded_value():
    """Catches checking before rounding: a value of 1000 plus noise below 1e-12 is 1000."""
    assert solve([option(DAY1, 1, 1000.0 + 1e-13)]) != []


def test_a_date_in_no_matchup_period_fails_naming_the_team_and_first_date():
    """Catches dropping such rows silently (R2.4): the build fails today, and must still,
    naming the team and the earliest date, whatever order the options arrive in."""
    options = [option(DAY2, 2, 3.0), option(DAY1, 1, 5.0), option(DAY3, 3, 1.0)]
    with pytest.raises(ValueError) as caught:
        solve(options, period=None)
    assert str(caught.value) == (
        f"optimal lineup failed for team-day {TEAM}, scoring_date=2026-06-01: "
        "its date is in no matchup period"
    )


def pitcher_days(*, actual):
    """Two days with one pitcher start each: player 5 is worth 5, player 6 worth 7."""
    return [
        option(DAY1, 5, 5.0, slot_id=10, start=True, actual=actual),
        option(DAY2, 6, 7.0, slot_id=10, start=True, actual=actual),
    ]


def test_the_cap_is_the_floor_of_the_start_limit():
    """Catches a cap that rounds a limit of 1.9 up to 2: with a cap of 1, only the better
    of the two starts is made."""
    rows = solve(pitcher_days(actual=False), limit=1.9)
    assert chosen(rows) == {(DAY2, 6)}


def test_a_limit_with_room_for_both_starts_makes_both():
    """Catches a cap that is always one start: a limit of 2.5 has a cap of 2, and the
    second start is worth 7 on the day the limit has not yet closed."""
    rows = solve(pitcher_days(actual=False), limit=2.5)
    assert chosen(rows) == {(DAY1, 5), (DAY2, 6)}


def test_actual_starts_above_the_limit_raise_the_cap():
    """Catches a cap below the actual lineup (R1.3): both starts were made, so the cap is
    2 though the limit is 1, and both are in the optimal lineup."""
    rows = solve(pitcher_days(actual=True), limit=1.0)
    assert chosen(rows) == {(DAY1, 5), (DAY2, 6)}


def test_a_team_period_error_names_the_team_and_the_matchup_period():
    """Catches an error from the period solve losing its context: a duplicate option is
    raised by the solver, and the entry point names the team and the period (R2.3)."""
    options = [option(DAY1, 1, 5.0), option(DAY1, 1, 4.0)]
    with pytest.raises(ValueError) as caught:
        solve(options, period=7)
    message = str(caught.value)
    assert message.startswith(f"optimal lineup failed for team-period {TEAM}, matchup_period=7: ")
    assert "duplicate option" in message


def test_the_rows_are_dicts_sorted_by_date_player_and_slot():
    """Catches a changed return shape: the SQL reads these three keys, and the rows come
    back in the order solve_team_period gives them."""
    options = [
        option(DAY2, 4, 2.0),
        option(DAY1, 9, 1.0, slot_id=10),
        option(DAY1, 3, 6.0),
        option(DAY2, 8, 1.0, slot_id=10),
    ]
    rows = solve(options)
    assert all(set(r) == {"scoring_date", "player_id", "slot_id"} for r in rows)
    keys = [(r["scoring_date"], r["player_id"], r["slot_id"]) for r in rows]
    assert keys == [(DAY1, 3, 1), (DAY1, 9, 10), (DAY2, 4, 1), (DAY2, 8, 10)]


def test_the_order_of_the_options_does_not_change_the_result():
    """Catches a result that depends on the input order: BigQuery and DuckDB aggregate the
    options in an order of their own (R3.6)."""
    options = [
        option(DAY1, 1, 4.0, actual=True),
        option(DAY1, 2, 4.0),
        option(DAY1, 7, 3.0, slot_id=10, start=True),
        option(DAY2, 1, 2.0),
        option(DAY2, 2, 6.0, actual=True),
        option(DAY2, 8, 3.0, slot_id=10, start=True, actual=True),
        option(DAY3, 2, 1.0),
        option(DAY3, 7, 3.0, slot_id=10, start=True),
    ]
    expected = solve(options, limit=1.0)
    rng = random.Random(137)
    for _ in range(10):
        shuffled = options[:]
        rng.shuffle(shuffled)
        assert solve(shuffled, limit=1.0) == expected


def test_the_file_can_be_a_udf_body():
    """Catches a construct that breaks the function body: dbt renders it as Jinja and
    BigQuery wraps it in a triple-quoted string, so neither delimiter may appear (ADR 0103);
    it must also parse as Python 3.11, the runtime BigQuery offers."""
    text = SOURCE.read_text()
    for forbidden in ("'''", "{{", "{%", "{#"):
        assert forbidden not in text
    ast.parse(text, feature_version=(3, 11))
