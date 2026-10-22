"""The optimal lineup of one team-day, as an assignment problem (spec 0012, ADR 0039).

Why this exists: a greedy pass in SQL double-assigns a player eligible at two slots, or
blocks a better lineup. Filling slots with players is an assignment problem, and SciPy
solves it exactly. This module builds the cost matrix and reads the answer back; it knows
nothing of dbt or the database, so pytest can test it on hand-built cases.

The rule (ADR 0037): the optimal lineup replaces a starter who played only with another
player who played. Its totals are therefore hindsight opportunity, not manager skill.

How the objective is built (R3.1, R3.2, R3.4):
  * Rows of the matrix are slot instances (a slot with count 2 is two rows).
  * Columns are the players, then "idle fillers": a slot matched to a filler is left idle.
  * Choosing the actual player of a slot, or leaving a slot idle, earns a bonus of 1e-9.
    That makes the tie-break (keep the actual lineup, else change the fewest slots) part
    of the objective, so the solver stays exact. A slot earns at most one bonus, so the
    summed value is within 1e-9 per slot of the greatest possible.
  * Fillers are limited, per role, to the slots of the role minus the actual starters who
    played on it. That enforces "at least as many players as the actual lineup had".
  * Rows and columns are sorted, so the result does not depend on the input order (R3.6).

The period (spec 0164, ADR 0090): a start is a pitcher-slot option with `is_start`, and a
league's start limit couples the days of a matchup period. `solve_team_day` therefore takes
two more arguments: `required_per_role` replaces the count of actual options as the per-role
minimum, and `forced` players must be assigned, exactly, by dummy rows in the matrix that can
absorb any column but a forced player's. A minimum or a forced set that cannot be met raises
`Infeasible`. `solve_team_period` solves each day once per set of starters used (the best
lineup whose starts are exactly that set, open or closed to starts by ESPN's rule), then a
dynamic programme over the starts so far picks one lineup per day within the start cap. The
per-day plan is kept when it scores as well as the best (R1.6).
"""

import itertools
import math
from datetime import date
from typing import NamedTuple

import numpy as np
from scipy.optimize import linear_sum_assignment

# The tie-break bonus is lost in a float sum of far larger values (R3.7).
TIE_BONUS = 1e-9
VALUE_BOUND = 1000.0
ROLES = ("hitter", "pitcher")


class Option(NamedTuple):
    """A legal (player, slot) pair and what it is worth; `role` is the slot's role."""

    player_id: int
    slot_id: int
    role: str
    value: float
    is_actual: bool
    is_start: bool = False  # a pitcher-slot option whose day_kind is 'start' (R1.7)


class Infeasible(ValueError):
    """No lineup meets the per-role minimum and the forced players of a team-day."""


class Slot(NamedTuple):
    """A lineup slot, with how many players the league lets it hold."""

    slot_id: int
    role: str
    count: int


def check_value_bound(options: list[Option]) -> None:
    """Raise ValueError naming the first option whose value is beyond VALUE_BOUND (R3.7)."""
    for o in options:
        if abs(o.value) > VALUE_BOUND:
            raise ValueError(
                f"option value out of bound (|value| > {VALUE_BOUND:g}): "
                f"player {o.player_id}, slot {o.slot_id}, value {o.value}"
            )


def solve_team_day(
    options: list[Option],
    slots: list[Slot],
    required_per_role: dict[str, int] | None = None,
    forced: frozenset[int] = frozenset(),
) -> list[tuple[int, int]]:
    """Return the optimal lineup as sorted (player_id, slot_id) pairs, real players only.

    `required_per_role`, when given, is the per-role minimum instead of the count of actual
    options; `forced` players must be assigned. Raises Infeasible if either cannot be met.
    """
    check_value_bound(options)
    if required_per_role is None:
        required_per_role = {
            r: sum(1 for o in options if o.is_actual and o.role == r) for r in ROLES
        }
    if not options and not any(required_per_role.values()):
        return []

    pair_cost: dict[tuple[int, int], float] = {}
    for o in options:
        key = (o.player_id, o.slot_id)
        if key in pair_cost:
            raise ValueError(f"duplicate option: player {o.player_id}, slot {o.slot_id}")
        pair_cost[key] = -(o.value + TIE_BONUS if o.is_actual else o.value)

    players = sorted({o.player_id for o in options})
    rows = [(s.slot_id, s.role) for s in sorted(slots) for _ in range(s.count)]
    if not forced <= set(players):
        raise Infeasible(f"forced players have no option: {sorted(forced - set(players))}")
    filler_counts = {
        role: sum(1 for _, r in rows if r == role) - required_per_role.get(role, 0)
        for role in ROLES
    }
    if any(n < 0 for n in filler_counts.values()):
        raise Infeasible(f"the minimum {required_per_role} exceeds the slots of a role")
    fillers = [role for role in ROLES for _ in range(filler_counts[role])]
    n_cols = len(players) + len(fillers)
    if n_cols < len(rows):
        raise Infeasible(f"{n_cols} players and fillers for {len(rows)} slots")

    # Dummy rows (only with forced players) make the matrix square, so every column is
    # matched; they cannot take a forced player's column, which only a slot row can match.
    n_dummy = n_cols - len(rows) if forced else 0
    cost = np.full((len(rows) + n_dummy, n_cols), math.inf)
    for i, (slot_id, role) in enumerate(rows):
        for j, player_id in enumerate(players):
            if (player_id, slot_id) in pair_cost:
                cost[i, j] = pair_cost[(player_id, slot_id)]
        for k, filler_role in enumerate(fillers):
            if filler_role == role:
                cost[i, len(players) + k] = -TIE_BONUS
    for i in range(len(rows), len(rows) + n_dummy):
        for j, player_id in enumerate(players):
            if player_id not in forced:
                cost[i, j] = 0.0
        cost[i, len(players) :] = 0.0

    try:
        row_ind, col_ind = linear_sum_assignment(cost)
    except ValueError as err:
        raise Infeasible(str(err)) from err
    if not np.isfinite(cost[row_ind, col_ind]).all():
        raise Infeasible("no assignment avoids a forbidden pair")
    return sorted(
        (players[j], rows[i][0])
        for i, j in zip(row_ind, col_ind, strict=True)
        if i < len(rows) and j < len(players)
    )


class Candidate(NamedTuple):
    """A lineup a day can field, the starts it uses and its score (credited value + 1e-9s)."""

    score: float
    starts: int
    lineup: tuple[tuple[int, int], ...]


def score_lineup(
    lineup: tuple[tuple[int, int], ...], options: list[Option], closed: bool, slot_instances: int
) -> float:
    """The credited value of a lineup (R1.2) plus the tie bonus of spec 0012, R3.1."""
    by_pair = {(o.player_id, o.slot_id): o for o in options}
    value, kept = 0.0, 0
    for pair in sorted(lineup):
        o = by_pair[pair]
        value += 0.0 if closed and o.is_start else o.value
        kept += o.is_actual
    return value + TIE_BONUS * (kept + (slot_instances - len(lineup)))


def count_starts(lineup: tuple[tuple[int, int], ...], options: list[Option]) -> int:
    starts = {(o.player_id, o.slot_id) for o in options if o.is_start}
    return sum(1 for pair in lineup if pair in starts)


def day_candidates(
    options: list[Option], slots: list[Slot], required: dict[str, int], closed: bool
) -> list[Candidate]:
    """Per set of starters used, the best lineup whose starts are exactly that set (step 3).

    A day closed to starts values every start at 0; its starts still count toward the cap.
    """
    slot_instances = sum(s.count for s in slots)
    starters = sorted({o.player_id for o in options if o.is_start})
    candidates: list[Candidate] = []
    seen: set[frozenset[tuple[int, int]]] = set()
    for k in range(len(starters), -1, -1):
        for chosen in itertools.combinations(starters, k):
            kept = [
                o._replace(value=0.0) if closed and o.is_start else o
                for o in options
                if o.is_start == (o.player_id in chosen)  # a chosen starter only starts
            ]
            try:
                lineup = tuple(
                    solve_team_day(
                        kept, slots, required_per_role=required, forced=frozenset(chosen)
                    )
                )
            except Infeasible:
                continue
            if frozenset(lineup) in seen:
                continue
            seen.add(frozenset(lineup))
            candidates.append(
                Candidate(
                    score_lineup(lineup, options, closed, slot_instances),
                    len(chosen),
                    lineup,
                )
            )
    return candidates


def solve_team_period(
    days: list[tuple[date, list[Option]]],
    slots: list[Slot],
    start_limit: float | None,
    start_cap: int | None,
) -> list[tuple[date, int, int]]:
    """Return the optimal lineups of a matchup period as sorted (date, player_id, slot_id).

    Maximises the credited value (R1.2) within `start_cap` starts. Raises Infeasible if no
    plan fits the cap.
    """
    ordered = sorted(days, key=lambda day: day[0])
    for _, options in ordered:
        check_value_bound(options)  # every day first (R1.8)
    if start_limit is None:
        return sorted(
            (scoring_date, player_id, slot_id)
            for scoring_date, options in ordered
            for player_id, slot_id in solve_team_day(options, slots)
        )
    if start_cap is None:
        raise ValueError("start_cap is required when start_limit is given")

    slot_instances = sum(s.count for s in slots)
    required = [
        {r: sum(1 for o in options if o.is_actual and o.role == r) for r in ROLES}
        for _, options in ordered
    ]
    cache: dict[tuple[int, bool], list[Candidate]] = {}

    # The state is the starts on earlier days; it maps to the best (score, plan) reaching it.
    states: dict[int, tuple[float, list[tuple[tuple[int, int], ...]]]] = {0: (0.0, [])}
    for index, (scoring_date, options) in enumerate(ordered):
        reached: dict[int, tuple[float, list[tuple[tuple[int, int], ...]]]] = {}
        for count in sorted(states):
            score, plan = states[count]
            closed = count >= start_limit
            if (index, closed) not in cache:
                cache[(index, closed)] = day_candidates(options, slots, required[index], closed)
            for candidate in cache[(index, closed)]:
                new_count = count + candidate.starts
                if new_count > start_cap:
                    continue
                new_score = score + candidate.score
                if new_count not in reached or new_score > reached[new_count][0]:
                    reached[new_count] = (new_score, [*plan, candidate.lineup])
        if not reached:
            raise Infeasible(
                f"no lineup on {scoring_date} keeps the period within {start_cap} starts"
            )
        states = reached
    best_count = min(states, key=lambda c: (-states[c][0], c))
    best_score, best_plan = states[best_count]

    # R1.6: today's per-day lineups, if within the cap and scoring at least as well.
    per_day = [tuple(solve_team_day(options, slots)) for _, options in ordered]
    per_day_starts = sum(
        count_starts(lineup, o) for lineup, (_, o) in zip(per_day, ordered, strict=True)
    )
    if per_day_starts <= start_cap:
        starts, per_day_score = 0, 0.0
        for lineup, (_, o) in zip(per_day, ordered, strict=True):
            per_day_score += score_lineup(lineup, o, starts >= start_limit, slot_instances)
            starts += count_starts(lineup, o)
        if per_day_score >= best_score:
            best_plan = per_day
    return sorted(
        (scoring_date, player_id, slot_id)
        for (scoring_date, _), lineup in zip(ordered, best_plan, strict=True)
        for player_id, slot_id in lineup
    )
