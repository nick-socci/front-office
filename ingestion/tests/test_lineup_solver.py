"""Tests for the optimal-lineup solver (spec 0012, R3 and R6.1; ADR 0039).

The solver is a plain function, so the cases are hand-built options and slots. Slot 1 and 2
are hitter slots, slot 10 is a pitcher slot unless a case says otherwise.
"""

import itertools
import random

import pytest

from lineup_solver import Option, Slot, solve_team_day

H, P = "hitter", "pitcher"
TIE_BONUS = 1e-9


def opt(player_id, slot_id, value, *, actual=False, role=H):
    return Option(player_id, slot_id, role, value, actual)


def hit(slot_id, count=1):
    return Slot(slot_id, H, count)


def pit(slot_id, count=1):
    return Slot(slot_id, P, count)


# --- brute force, written independently of the solver's matrix ---------------------------


def legal_lineups(options, slots):
    """Every lineup R3.1 allows: a set of (player, slot) pairs, built player by player."""
    capacity = {s.slot_id: s.count for s in slots}
    role_of = {s.slot_id: s.role for s in slots}
    floor = {H: 0, P: 0}
    for o in options:
        if o.is_actual:
            floor[o.role] += 1
    players = sorted({o.player_id for o in options})
    choices = [
        [None] + [(o.player_id, o.slot_id) for o in options if o.player_id == p] for p in players
    ]
    for picks in itertools.product(*choices):
        lineup = [x for x in picks if x is not None]
        if is_legal(lineup, options, capacity, role_of, floor):
            yield lineup


def is_legal(lineup, options, capacity, role_of, floor):
    pairs = {(o.player_id, o.slot_id) for o in options}
    if len({p for p, _ in lineup}) != len(lineup) or not set(lineup) <= pairs:
        return False
    for slot_id, cap in capacity.items():
        if sum(1 for _, s in lineup if s == slot_id) > cap:
            return False
    return all(sum(1 for _, s in lineup if role_of[s] == r) >= n for r, n in floor.items())


def total(lineup, options):
    value = {(o.player_id, o.slot_id): o.value for o in options}
    return sum(value[pair] for pair in lineup)


def actual_lineup(options):
    return sorted((o.player_id, o.slot_id) for o in options if o.is_actual)


# --- hand-built cases -------------------------------------------------------------------


def test_player_eligible_at_two_slots_is_not_double_assigned():
    # Catches a greedy pass: it gives A (5 at slot 1) the best slot, leaving B nowhere, for 5;
    # the optimum is B at slot 1 and A at slot 2, for 7.
    options = [
        opt(1, 1, 5.0, actual=True),
        opt(1, 2, 4.0),
        opt(2, 1, 3.0),
    ]
    assert solve_team_day(options, [hit(1), hit(2)]) == [(1, 2), (2, 1)]


def test_slot_with_count_above_one_holds_that_many():
    # Catches a count ignored (one player only) or exceeded (all four): the best three win.
    options = [
        opt(1, 1, 1.0, actual=True),
        opt(2, 1, 2.0, actual=True),
        opt(3, 1, 3.0, actual=True),
        opt(4, 1, 5.0),
    ]
    assert solve_team_day(options, [hit(1, 3)]) == [(2, 1), (3, 1), (4, 1)]


def test_starter_with_bad_day_and_no_replacement_stays():
    # Catches dropping a negative-valued starter: R3.1's floor keeps him in the lineup.
    options = [opt(1, 1, -2.0, actual=True)]
    assert solve_team_day(options, [hit(1)]) == [(1, 1)]


def test_starter_with_bad_day_is_replaced_by_bench_player_who_played():
    # Catches a replacement ignored: the bench player's better day takes the slot.
    options = [opt(1, 1, -2.0, actual=True), opt(2, 1, 0.5)]
    assert solve_team_day(options, [hit(1)]) == [(2, 1)]


def test_starter_with_no_game_is_displaced_by_bench_player_with_one():
    # Catches an idle slot left empty: the starter has no option, so the slot was idle and
    # the bench player who played fills it.
    options = [opt(2, 1, 1.5)]
    assert solve_team_day(options, [hit(1)]) == [(2, 1)]


def test_two_way_player_takes_one_slot_only():
    # Catches a two-way player used in both roles: he is worth more as a pitcher (4), so
    # the hitter slot goes to the other hitter, and he is never given both.
    options = [
        opt(1, 1, 3.0, actual=True),
        opt(1, 10, 4.0, role=P),
        opt(2, 1, 2.5),
    ]
    assert solve_team_day(options, [hit(1), pit(10)]) == [(1, 10), (2, 1)]


def test_tie_keeps_the_actual_lineup():
    # Catches a tie broken arbitrarily: equal value everywhere, so the actual lineup stays.
    options = [
        opt(1, 1, 1.0),
        opt(1, 2, 1.0),
        opt(2, 1, 1.0, actual=True),
        opt(2, 2, 1.0),
        opt(3, 1, 1.0),
        opt(3, 2, 1.0, actual=True),
    ]
    assert solve_team_day(options, [hit(1), hit(2)]) == [(2, 1), (3, 2)]


@pytest.mark.parametrize("bench_value", [0.0, 1e-10])
def test_bench_player_worth_less_than_the_bonus_does_not_fill_an_idle_slot(bench_value):
    # Catches an idle slot treated as worthless: leaving it idle earns 1e-9, which a bench
    # player worth 0 or 1e-10 cannot beat, so neither is brought in.
    options = [opt(1, 1, 1.0, actual=True), opt(2, 1, bench_value), opt(3, 1, bench_value)]
    assert solve_team_day(options, [hit(1, 2)]) == [(1, 1)]


def test_bench_player_worth_the_bonus_or_more_fills_an_idle_slot():
    # Catches a bonus too large: a gain well above 1e-9 does fill the idle slot.
    options = [opt(1, 1, 1.0, actual=True), opt(2, 1, 0.01)]
    assert solve_team_day(options, [hit(1, 2)]) == [(1, 1), (2, 1)]


def test_values_at_the_bound_keep_the_actual_lineup_and_respect_eligibility():
    # Catches the bonus lost at 1,000 (2,000 summed), a forbidden pair costed as a number,
    # and input order mattering: the actual players are in reverse order of id (2 holds slot 1,
    # 1 holds slot 2), every swap ties, and the pitcher slot is out of the hitters' reach.
    options = [
        opt(1, 1, 1000.0),
        opt(1, 2, 1000.0, actual=True),
        opt(2, 1, 1000.0, actual=True),
        opt(2, 2, 1000.0),
        opt(3, 1, -1000.0),
        opt(4, 10, 1000.0, actual=True, role=P),
    ]
    slots = [hit(1), hit(2), pit(10)]
    assert solve_team_day(options, slots) == [(1, 2), (2, 1), (4, 10)]
    assert solve_team_day(options[::-1], slots[::-1]) == [(1, 2), (2, 1), (4, 10)]


@pytest.mark.parametrize("value", [1000.001, -1000.001])
def test_value_above_the_bound_raises_naming_player_slot_and_value(value):
    # Catches R3.7 unenforced: past 1,000 the 1e-9 terms are lost to rounding.
    options = [opt(7, 1, 1.0, actual=True), opt(8, 2, value)]
    with pytest.raises(ValueError, match=rf"player 8.*slot 2.*{abs(value)}"):
        solve_team_day(options, [hit(1), hit(2)])


def test_two_equal_lineups_that_each_change_two_slots_give_the_same_one_always():
    # Catches input-order dependence between equal lineups: c and d may take either slot, and
    # whichever is chosen must not depend on how the rows arrive.
    options = [
        opt(1, 1, 1.0, actual=True),
        opt(2, 2, 1.0, actual=True),
        opt(3, 1, 3.0),
        opt(3, 2, 3.0),
        opt(4, 1, 3.0),
        opt(4, 2, 3.0),
    ]
    slots = [hit(1), hit(2)]
    first = solve_team_day(options, slots)
    assert first in ([(3, 1), (4, 2)], [(3, 2), (4, 1)])
    rng = random.Random(12)
    for _ in range(25):
        shuffled = options[:]
        rng.shuffle(shuffled)
        assert solve_team_day(shuffled, slots[::-1]) == first


def test_team_day_with_no_options_returns_nothing():
    # Catches a crash on an empty matrix: the optimal lineup is the empty one.
    assert solve_team_day([], [hit(1), hit(2), pit(10)]) == []
    assert solve_team_day([], []) == []


def test_input_row_order_does_not_change_the_result():
    # Catches any dependence on row order (R3.6) on a case with many ties and a count of 2.
    options = [
        opt(1, 1, 2.0, actual=True),
        opt(1, 2, 2.0),
        opt(2, 1, 2.0),
        opt(2, 2, 2.0, actual=True),
        opt(3, 2, 2.0, actual=True),
        opt(3, 1, 2.0),
        opt(4, 1, 2.0),
        opt(4, 2, 2.0),
        opt(5, 10, 1.0, actual=True, role=P),
        opt(6, 10, 1.0, role=P),
    ]
    slots = [hit(1), hit(2, 2), pit(10)]
    expected = solve_team_day(options, slots)
    rng = random.Random(6)
    for _ in range(50):
        shuffled_options, shuffled_slots = options[:], slots[:]
        rng.shuffle(shuffled_options)
        rng.shuffle(shuffled_slots)
        assert solve_team_day(shuffled_options, shuffled_slots) == expected


# --- random small cases against brute force ------------------------------------------------


def random_case(rng):
    slots = [hit(1, rng.randint(1, 2)), hit(2, rng.randint(1, 2))]
    if rng.random() < 0.6:
        slots.append(pit(10, rng.randint(1, 2)))
    slots = slots[: rng.randint(1, len(slots))]
    free = {s.slot_id: s.count for s in slots}
    n_players = rng.randint(2, 5)
    options, taken = [], set()
    for player_id in range(1, n_players + 1):
        eligible = [s for s in slots if rng.random() < 0.6]
        # Values on a half-step grid so ties are common and the sums are exact.
        made = [
            Option(player_id, s.slot_id, s.role, rng.choice([-1, 0, 0.5, 1, 1, 2]), False)
            for s in eligible
        ]
        if made and rng.random() < 0.6:
            pick = rng.randrange(len(made))
            if free[made[pick].slot_id] > 0:
                free[made[pick].slot_id] -= 1
                made[pick] = made[pick]._replace(is_actual=True)
                taken.add(player_id)
        options.extend(made)
    return options, slots


def test_random_cases_are_within_the_bound_of_the_brute_force_maximum():
    # Catches a wrong matrix (forbidden pairs, fillers, floors) that hand-built cases miss:
    # the solver's lineup is legal and its value is within 1e-9 per slot instance of the best
    # of every legal lineup; when the actual lineup attains the best it is returned (R3.4).
    rng = random.Random(20261009)
    kept_actual = 0
    for _ in range(400):
        options, slots = random_case(rng)
        capacity = {s.slot_id: s.count for s in slots}
        role_of = {s.slot_id: s.role for s in slots}
        floor = {r: sum(1 for o in options if o.is_actual and o.role == r) for r in (H, P)}
        result = solve_team_day(options, slots)
        assert result == sorted(result)
        assert is_legal(result, options, capacity, role_of, floor), (options, slots, result)
        best = max(total(lineup, options) for lineup in legal_lineups(options, slots))
        slot_instances = sum(s.count for s in slots)
        assert total(result, options) >= best - TIE_BONUS * slot_instances, (options, slots)
        if total(actual_lineup(options), options) == best:
            kept_actual += 1
            assert result == actual_lineup(options), (options, slots, result)
    assert kept_actual > 20  # the R3.4 branch is exercised, not vacuous
