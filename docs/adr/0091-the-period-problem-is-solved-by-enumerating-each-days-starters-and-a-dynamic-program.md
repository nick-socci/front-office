# 0091. The period problem is solved by enumerating each day's starters and a dynamic program

- Status: accepted
- Date: 2026-10-21
- Spec: [0164-optimal-lineup-per-matchup-period](../specs/0164-optimal-lineup-per-matchup-period/design.md) · Issue: #164

## Context

ADR 0090 couples a team's days within a matchup period through a cap on starts, and,
where the actual lineup went past the limit, through ESPN's crediting of starts past it. Spec 0012
needs the solve to be exact, with a 1e-9 tie-break per slot that keeps the actual lineup
on a tie (R3.2, R3.4) and a no-churn test that relies on it (R4.8). Today each day is one
assignment problem, solved exactly by `scipy.optimize.linear_sum_assignment` (ADR 0039).
A team-day has at most 6 starting pitchers (spec 0164, C4).

## Decision drivers

- Exact, with the tie-break intact.
- ESPN's rule as it is, including the day that reaches the limit finishing.
- Reuse the tested per-day solver.
- Cheap on eight seasons.

## Considered options

1. **Enumerate and DP.** For each day and each subset of its starting pitchers, solve the
   day's best assignment that starts exactly that subset, with starts counted as credited
   (0 on a day past the limit). A dynamic program over the days, with the state the starts
   so far, picks the best credited plan within the cap.
2. **MILP.** One mixed-integer program per team-period (`scipy.optimize.milp`, HiGHS).
3. **Lagrangian.** A price on starts, adjusted until the per-day assignments respect the
   limit.

## Decision

Chosen by the owner on 2026-10-21, as recommended: **option 1**. Every candidate is an exact
assignment and the DP is exhaustive over start counts, so the plan is exact. The tie-break
survives, because scores are compared as the per-day solver computes them, and the subset
is forced exactly, not by a penalty. The candidates must be the sets of starters *used*:
sets merely *allowed* miss a plan that takes a worse start today to make a worse one
tomorrow count 0 (C16). The 2ⁿ enumeration is at most 64 solves a day on real data, and a
synthetic 12-starter day takes 0.43 s (C17). All 2,340 team-periods solve in about
3.5 s (C11).

Option 2 is the textbook formulation, but SciPy exposes only its relative gap (C15), and
whether it separates plans 1e-9 apart is unmeasured. Option 3 is not exact, and the
finishing day cannot be expressed as a price.

## Consequences

- Good: `solve_team_day` is reused, with two additions: the role minimum can be passed in,
  and a set of players forced in. Without the first, a sub-problem that removes starters
  lowers its own minimum, as the prototype's first version did (C13).
- Good: the plan is deterministic. Subsets, states and ties are taken in a stated order.
- Bad / accepted cost: the cost grows as 2ⁿ in a day's starting pitchers, with no cap.
  Measured to 12 (0.43 s a day, C17). Scaled from that, 20 starters on one team-day would
  take about 110 s. Real data has at most 6 (C4).
- Follow-ups: none.
