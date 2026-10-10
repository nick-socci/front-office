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
"""

import math
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


class Slot(NamedTuple):
    """A lineup slot, with how many players the league lets it hold."""

    slot_id: int
    role: str
    count: int


def solve_team_day(options: list[Option], slots: list[Slot]) -> list[tuple[int, int]]:
    """Return the optimal lineup as sorted (player_id, slot_id) pairs, real players only."""
    for o in options:
        if abs(o.value) > VALUE_BOUND:
            raise ValueError(
                f"option value out of bound (|value| > {VALUE_BOUND:g}): "
                f"player {o.player_id}, slot {o.slot_id}, value {o.value}"
            )
    if not options:
        return []

    pair_cost: dict[tuple[int, int], float] = {}
    for o in options:
        key = (o.player_id, o.slot_id)
        if key in pair_cost:
            raise ValueError(f"duplicate option: player {o.player_id}, slot {o.slot_id}")
        pair_cost[key] = -(o.value + TIE_BONUS if o.is_actual else o.value)

    players = sorted({o.player_id for o in options})
    rows = [(s.slot_id, s.role) for s in sorted(slots) for _ in range(s.count)]
    actual_per_role = {r: sum(1 for o in options if o.is_actual and o.role == r) for r in ROLES}
    fillers = [
        role
        for role in ROLES
        for _ in range(sum(1 for _, r in rows if r == role) - actual_per_role[role])
    ]

    cost = np.full((len(rows), len(players) + len(fillers)), math.inf)
    for i, (slot_id, role) in enumerate(rows):
        for j, player_id in enumerate(players):
            if (player_id, slot_id) in pair_cost:
                cost[i, j] = pair_cost[(player_id, slot_id)]
        for k, filler_role in enumerate(fillers):
            if filler_role == role:
                cost[i, len(players) + k] = -TIE_BONUS

    row_ind, col_ind = linear_sum_assignment(cost)
    return sorted(
        (players[j], rows[i][0]) for i, j in zip(row_ind, col_ind, strict=True) if j < len(players)
    )
