"""Tests for the optimal-lineup solver (spec 0012, R3 and R6.1; ADR 0039).

The solver is a plain function, so the cases are hand-built options and slots. Slot 1 and 2
are hitter slots, slot 10 is a pitcher slot unless a case says otherwise.
"""

import itertools
import math
import random
from datetime import date

import pytest

from solve_lineup_period import (
    Infeasible,
    Option,
    Slot,
    check_value_bound,
    solve_team_day,
    solve_team_period,
)

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


# --- the value bound, as the model calls it before skipping an unvalued team-day (R3.7) ----


def test_check_value_bound_passes_values_in_bound_including_exactly_the_bound():
    """Catches a bound that rejects the boundary itself or a value well inside it."""
    check_value_bound([opt(1, 1, 0.0), opt(2, 1, 1000.0), opt(3, 1, -1000.0), opt(4, 1, 12.5)])


def test_check_value_bound_raises_naming_player_slot_and_value():
    """Catches a bound that fails without saying which option breached it."""
    with pytest.raises(ValueError, match=r"player 7, slot 2, value 1000\.5"):
        check_value_bound([opt(1, 1, 3.0), opt(7, 2, 1000.5)])
    with pytest.raises(ValueError, match="out of bound"):
        check_value_bound([opt(8, 1, -1001.0)])


# --- the team-day solver's additions: a stated minimum, forced players, is_start (spec 0164) --


def popt(player_id, slot_id, value, *, actual=False, start=False):
    """A pitcher-slot option; `start` marks a day_kind 'start' (R1.7)."""
    return Option(player_id, slot_id, P, value, actual, start)


def day(n):
    return date(2026, 4, n)


def test_option_is_not_a_start_unless_it_says_so():
    # Catches a default that makes every existing caller's option a start.
    assert opt(1, 1, 1.0).is_start is False
    assert popt(1, 10, 1.0, start=True).is_start is True


def test_infeasible_is_a_value_error():
    # Catches a new exception type the model's ValueError handling would miss.
    assert issubclass(Infeasible, ValueError)


def test_required_per_role_replaces_the_count_of_actual_options():
    # Catches the minimum still read from is_actual: no option is actual, yet one hitter is
    # required, so the better of two negative hitters must be assigned (default gives none).
    options = [opt(1, 1, -3.0), opt(2, 1, -2.0)]
    assert solve_team_day(options, [hit(1, 2)]) == []
    assert solve_team_day(options, [hit(1, 2)], required_per_role={H: 1}) == [(2, 1)]


def test_forced_player_is_assigned_even_when_worse_than_leaving_him_out():
    # Catches forcing done by a penalty or ignored: player 2 is worth -1 and the slot has
    # a better player, yet player 2 must be assigned, and the other slot goes to the best rest.
    options = [opt(1, 1, 5.0, actual=True), opt(2, 1, -1.0), opt(3, 1, 3.0)]
    assert solve_team_day(options, [hit(1)], forced=frozenset({2})) == [(2, 1)]
    assert solve_team_day(options, [hit(1, 2)], forced=frozenset({2})) == [(1, 1), (2, 1)]


def test_forced_players_that_do_not_fit_raise_infeasible():
    # Catches a silent drop of a forced player: two players forced into one place.
    options = [opt(1, 1, 1.0), opt(2, 1, 1.0)]
    with pytest.raises(Infeasible):
        solve_team_day(options, [hit(1)], forced=frozenset({1, 2}))


def test_forced_player_with_no_option_raises_infeasible():
    # Catches a forced player who is not among the options being ignored.
    with pytest.raises(Infeasible):
        solve_team_day([opt(1, 1, 1.0)], [hit(1)], forced=frozenset({9}))


def test_a_minimum_that_cannot_be_met_raises_infeasible():
    # Catches a short lineup returned silently: one player for a minimum of two, a minimum
    # above the slots, and a slot nobody is eligible for.
    slots = [hit(1, 2)]
    with pytest.raises(Infeasible):
        solve_team_day([opt(1, 1, 1.0)], slots, required_per_role={H: 2})
    with pytest.raises(Infeasible):
        solve_team_day([opt(1, 1, 1.0), opt(2, 1, 1.0)], slots, required_per_role={H: 3})
    with pytest.raises(Infeasible):
        solve_team_day([], slots, required_per_role={H: 1})
    with pytest.raises(Infeasible):
        solve_team_day([opt(1, 1, 1.0), opt(2, 1, 1.0)], [hit(1), hit(2)], required_per_role={H: 2})


# --- the period solver: hand-built cases (spec 0164, R5.1) ------------------------------------
# Pitcher slot 10 holds one unless a case says otherwise; start_limit and start_cap are given.


def test_period_cap_binds_and_the_best_start_is_kept():
    # Catches a cap not enforced, or the first start kept instead of the best: two days, one
    # start allowed; the 5 on day 2 beats the 3 on day 1, day 1 goes to the reliever.
    days = [
        (day(1), [popt(1, 10, 3.0, start=True), popt(9, 10, 0.0, actual=True)]),
        (day(2), [popt(2, 10, 5.0, start=True), popt(9, 10, 0.0, actual=True)]),
    ]
    assert solve_team_period(days, [pit(10)], 1.0, 1) == [(day(1), 9, 10), (day(2), 2, 10)]


def test_period_slot_a_start_would_take_goes_to_a_reliever_or_another_player():
    # Catches a start kept past a zero cap: the start (5) is forbidden, so the slot goes to the
    # reliever (1), and with two slots the second goes to the other reliever (0.5).
    one = [(day(1), [popt(1, 10, 5.0, start=True), popt(2, 10, 1.0, actual=True)])]
    assert solve_team_period(one, [pit(10)], 0.5, 0) == [(day(1), 2, 10)]
    two = [
        (
            day(1),
            [
                popt(1, 10, 5.0, start=True),
                popt(2, 10, 1.0, actual=True),
                popt(3, 10, 0.5),
            ],
        )
    ]
    assert solve_team_period(two, [pit(10, 2)], 0.5, 0) == [(day(1), 2, 10), (day(1), 3, 10)]


def test_period_non_whole_limit_opens_a_day_after_one_start_and_closes_after_two():
    # Catches 1 < 1.5 read as closed, or a third start allowed: with a cap of 2 the best two
    # of three starts (2 and 4) are taken, the second on a day that is open after one start.
    days = [
        (day(1), [popt(1, 10, 1.0, start=True), popt(9, 10, 0.0, actual=True)]),
        (day(2), [popt(2, 10, 2.0, start=True), popt(9, 10, 0.0, actual=True)]),
        (day(3), [popt(3, 10, 4.0, start=True), popt(9, 10, 0.0, actual=True)]),
    ]
    assert solve_team_period(days, [pit(10)], 1.5, 2) == [
        (day(1), 9, 10),
        (day(2), 2, 10),
        (day(3), 3, 10),
    ]


def test_period_limit_29_857_caps_at_29_and_compares_exactly():
    # Catches a cap rounded up (30) or a limit rounded: 30 days with a start worth the day
    # number; the 29 best are taken (days 2 to 30), all open, day 1 goes to the reliever.
    days = [
        (day(n), [popt(100 + n, 10, float(n), start=True), popt(9, 10, 0.0, actual=True)])
        for n in range(1, 31)
    ]
    plan = solve_team_period(days, [pit(10)], 29.857, 29)
    assert [(d, p) for d, p, _ in plan if p != 9] == [(day(n), 100 + n) for n in range(2, 31)]
    assert (day(1), 9, 10) in plan


def test_period_actual_past_the_limit_start_on_a_closed_day_counts_zero():
    # Catches a closed-day start credited in full: the cap is 2 (the actual lineup's starts)
    # over a limit of 1. Day 2 is closed after day 1's start, so the start worth 50 counts 0
    # and the reliever worth 0.5 is chosen.
    days = [
        (day(1), [popt(1, 10, 1.0, actual=True, start=True)]),
        (day(2), [popt(2, 10, 50.0, actual=True, start=True), popt(3, 10, 0.5)]),
    ]
    assert solve_team_period(days, [pit(10)], 1.0, 2) == [(day(1), 1, 10), (day(2), 3, 10)]


def test_period_takes_a_worse_start_today_so_that_a_worse_one_tomorrow_counts_zero():
    # Catches candidates that miss a plan (C16): limit 1, cap 2. Day 1 reliever 0 or start -1,
    # day 2 only a start worth -10. Starting on day 1 closes day 2: -1 + 0, not 0 + -10.
    days = [
        (day(1), [popt(1, 10, 0.0, actual=True), popt(2, 10, -1.0, start=True)]),
        (day(2), [popt(3, 10, -10.0, actual=True, start=True)]),
    ]
    assert solve_team_period(days, [pit(10)], 1.0, 2) == [(day(1), 2, 10), (day(2), 3, 10)]


def test_period_near_tie_prefers_the_better_plan_over_the_per_day_plan():
    # Catches a tolerance in the per-day comparison (review round 2 F1): the per-day plan
    # 1, 3, 6 is beaten by 1, 4, 6 by 3e-10 (player 3's start is closed and counts 0), and the
    # better plan must win, though the gap is below the 5e-10 gap the mart treats as none.
    days = [
        (day(1), [popt(1, 10, 1.0, actual=True, start=True)]),
        (
            day(2),
            [
                popt(2, 10, -1.0, actual=True),
                popt(3, 10, 5.0, start=True),
                popt(4, 10, 3e-10),
            ],
        ),
        (day(3), [popt(5, 10, 0.5, actual=True, start=True), popt(6, 10, 0.6)]),
    ]
    slots = [pit(10)]
    assert solve_team_day(days[1][1], slots) == [(3, 10)]  # the per-day plan: not vacuous
    assert solve_team_period(days, slots, 1.0, 2) == [
        (day(1), 1, 10),
        (day(2), 4, 10),
        (day(3), 6, 10),
    ]


def test_period_without_a_limit_is_the_per_day_lineups():
    # Catches a period rule leaking into leagues with no limit (R1.4): days out of order.
    days = [
        (day(2), [popt(2, 10, 5.0, start=True), popt(9, 10, 0.0, actual=True), opt(4, 1, 1.0)]),
        (day(1), [popt(1, 10, 3.0, start=True), popt(9, 10, 4.0, actual=True), opt(4, 1, 2.0)]),
    ]
    slots = [hit(1), pit(10)]
    expected = sorted((d, p, s) for d, options in days for p, s in solve_team_day(options, slots))
    assert solve_team_period(days, slots, None, None) == expected


def test_period_ties_keep_the_actual_lineup():
    # Catches a tie broken by order: every option is worth 1, the cap binds at one start, and
    # the actual lineup (a reliever, then a start) is returned.
    days = [
        (day(1), [popt(1, 10, 1.0, start=True), popt(3, 10, 1.0, actual=True), popt(5, 10, 1.0)]),
        (day(2), [popt(2, 10, 1.0, actual=True, start=True), popt(1, 10, 1.0, start=True)]),
    ]
    assert solve_team_period(days, [pit(10)], 1.0, 1) == [(day(1), 3, 10), (day(2), 2, 10)]


def test_period_input_order_does_not_change_the_result():
    # Catches any dependence on the order of days, options or slots, on a case of ties:
    # two equal starters a day and one start allowed in the period.
    days = [
        (day(1), [popt(1, 10, 3.0, start=True), popt(2, 10, 3.0, start=True), opt(7, 1, 1.0)]),
        (day(2), [popt(3, 10, 3.0, start=True), popt(4, 10, 3.0, start=True), opt(7, 1, 1.0)]),
        (day(3), [popt(5, 10, 0.0, actual=True), opt(8, 1, 1.0, actual=True)]),
    ]
    slots = [hit(1), pit(10)]
    expected = solve_team_period(days, slots, 1.0, 1)
    rng = random.Random(77)
    for _ in range(40):
        shuffled = [(d, rng.sample(options, len(options))) for d, options in days]
        rng.shuffle(shuffled)
        assert solve_team_period(shuffled, rng.sample(slots, len(slots)), 1.0, 1) == expected


def test_period_two_way_hitter_option_is_not_a_start_and_costs_no_start():
    # Catches a hitter-slot option counted as a start (R1.7): with a cap of 0 the starter
    # cannot start, but his hitter option (worth 4) is no start and is taken.
    options = [
        popt(1, 10, 3.0, start=True),
        opt(1, 1, 4.0),
        popt(2, 10, 1.0, actual=True),
    ]
    assert solve_team_period([(day(1), options)], [hit(1), pit(10)], 0.5, 0) == [
        (day(1), 1, 1),
        (day(1), 2, 10),
    ]


@pytest.mark.parametrize("limit", [None, 1.0])
def test_period_value_beyond_the_bound_on_any_day_raises_before_solving(limit):
    # Catches the bound checked only on the day being solved (R1.8): the bad value is on the
    # last day, and the error is the bound's, not an Infeasible from an earlier day.
    days = [
        (day(1), [popt(1, 10, 1.0, actual=True)]),
        (day(2), [popt(8, 10, 1000.5, actual=True)]),
    ]
    with pytest.raises(ValueError, match=r"out of bound.*player 8") as raised:
        solve_team_period(days, [pit(10)], limit, None if limit is None else 1)
    assert not isinstance(raised.value, Infeasible)


# --- random small periods against a brute force over every plan ------------------------------


def credited(by_day, options_by_day, limit):
    """R1.2: walk the days in order; a day is closed when earlier starts are at the limit."""
    starts, value = 0, 0.0
    for d in sorted(by_day):
        info = {(o.player_id, o.slot_id): o for o in options_by_day[d]}
        closed = starts >= limit
        for pair in sorted(by_day[d]):
            o = info[pair]
            value += 0.0 if closed and o.is_start else o.value
            starts += o.is_start
    return value


def bonuses(by_day, options_by_day, slots):
    """How many 1e-9 bonuses a plan earns: players in their actual slot and idle slots."""
    n = 0
    for d, lineup in by_day.items():
        actual = {(o.player_id, o.slot_id) for o in options_by_day[d] if o.is_actual}
        n += sum(1 for pair in lineup if pair in actual)
        n += sum(s.count for s in slots) - len(lineup)
    return n


def period_starts(by_day, options_by_day):
    return sum(
        o.is_start
        for d in by_day
        for o in options_by_day[d]
        if (o.player_id, o.slot_id) in set(by_day[d])
    )


def random_period(rng):
    """Two or three days of pitchers (starts and relievers), hitters and some two-way players."""
    slots = [hit(1, rng.randint(1, 2)), pit(10, rng.randint(1, 2))]
    days = []
    for n in range(rng.randint(2, 3)):
        free = {1: slots[0].count, 10: slots[1].count}
        options = []
        for k in range(rng.randint(2, 4)):
            pid = 10 * n + k + 1
            value = rng.choice([-2, -1, 0, 0.5, 1, 2, 3, 5])
            if rng.random() < 0.65:
                start = rng.random() < 0.5
                actual = free[10] > 0 and rng.random() < 0.5
                free[10] -= actual
                options.append(popt(pid, 10, value, actual=actual, start=start))
                if start and rng.random() < 0.2:  # a two-way player: a hitter option, no start
                    options.append(opt(pid, 1, rng.choice([-1, 0.5, 2, 4])))
            else:
                actual = free[1] > 0 and rng.random() < 0.5
                free[1] -= actual
                options.append(opt(pid, 1, value, actual=actual))
        days.append((day(n + 1), options))
    return days, slots


def test_random_periods_are_within_the_bound_of_the_brute_force_maximum():
    # Catches a wrong DP state, cap, candidate set or crediting that hand-built cases miss:
    # the plan is legal on every day, within the cap, and credited within 1e-9 per slot-day
    # of the best of every plan; the per-day plan is returned when it is within the cap and
    # ties the best on credited value and on bonuses.
    rng = random.Random(20261021)
    binding = per_day_returned = 0
    for _ in range(300):
        days, slots = random_period(rng)
        limit = rng.choice([0.5, 1.0, 1.5, 2.0, 2.857, 3.0])
        options_by_day = dict(days)
        actual_starts = sum(o.is_actual and o.is_start for _, options in days for o in options)
        cap = max(math.floor(limit), actual_starts)
        capacity = {s.slot_id: s.count for s in slots}
        role_of = {s.slot_id: s.role for s in slots}

        result = solve_team_period(days, slots, limit, cap)
        assert result == sorted(result)
        by_day = {d: [(p, s) for dd, p, s in result if dd == d] for d, _ in days}
        for d, options in days:
            floor = {r: sum(1 for o in options if o.is_actual and o.role == r) for r in (H, P)}
            assert is_legal(by_day[d], options, capacity, role_of, floor), (days, slots, result)
        assert period_starts(by_day, options_by_day) <= cap, (days, slots, result)

        # The best plan by credited value, and among those the most 1e-9 bonuses (R1.1).
        best, best_bonus = -math.inf, 0
        for plan in itertools.product(*(list(legal_lineups(o, slots)) for _, o in days)):
            plan_by_day = {d: lineup for (d, _), lineup in zip(days, plan, strict=True)}
            if period_starts(plan_by_day, options_by_day) <= cap:
                key = (
                    credited(plan_by_day, options_by_day, limit),
                    bonuses(plan_by_day, options_by_day, slots),
                )
                best, best_bonus = max((best, best_bonus), key)
        slot_days = len(days) * sum(s.count for s in slots)
        got = credited(by_day, options_by_day, limit)
        assert got >= best - TIE_BONUS * slot_days, (days, slots, limit, cap, result)

        per_day = {d: solve_team_day(o, slots) for d, o in days}
        if period_starts(per_day, options_by_day) > cap:
            binding += 1
        elif (
            credited(per_day, options_by_day, limit),
            bonuses(per_day, options_by_day, slots),
        ) == (best, best_bonus):
            per_day_returned += 1
            expected = sorted((d, p, s) for d, lineup in per_day.items() for p, s in lineup)
            assert result == expected, (days, slots, limit, cap, result)
    assert binding > 40  # caps do bind: the generator is not vacuous
    assert per_day_returned > 40  # the R1.6 branch is exercised
