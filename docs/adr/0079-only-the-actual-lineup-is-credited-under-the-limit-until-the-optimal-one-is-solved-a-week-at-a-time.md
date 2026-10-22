# 0079. Only the actual lineup is credited under the limit, until the optimal one is solved a week at a time

- Status: superseded by [0090](0090-the-optimal-lineup-is-chosen-per-matchup-period-within-the-start-limit.md)
- Date: 2026-10-18
- Spec: [0152-games-started-limit](../specs/0152-games-started-limit/design.md) · Issue: #152
- Supersedes: [0073](0073-both-lineups-totals-are-credited-under-the-limit.md)
- Amends: [0037](0037-the-optimal-lineup-replaces-a-played-starter-only-with-a-player-who-played.md), for how the actual lineup's totals and values are credited

## Context

ADR 0073 credited both lineups' totals and values under the games-started limit, with each
lineup counting its own starts, while the solver still chose each team-day alone
(ADR 0037). The build of spec 0152 on the eight real seasons showed that this can make
the "optimal" lineup worse than the actual one. In 2022, matchup period 18, team 1, the
solver adds a start on 08-20 (+0.104 in day value). That takes the team to the limit of
13, so its start on 08-21 is not credited (−0.299). `value_gap` on 08-21 is −0.299, the
period is −0.194, and `fct_lineup_decisions_are_never_worse_than_the_actual_lineup`
(spec 0012, R4.7) fails. A limit applied after a per-day solve can punish the solver for
a choice it was never told was costly.

The actual lineup must still be limited. Its totals are tested equal to the scored totals,
and its value is a sum of day values that add back to the season values (spec 0152, C13
and C18).

## Decision drivers

- The optimal lineup is never worse than the actual one (R4.7 of spec 0012).
- The actual lineup is credited as ESPN credits it.
- What the owner wants (2026-10-18): the optimal lineup's starts are the best starts of a
  week that stay within the limit. That needs a solver that sees the week, which is more
  than this spec covers.

## Considered options

1. **Both lineups limited, R4.7 judged on the unlimited sums.** Keeps ADR 0073, and lets
   `value_gap` go below zero where the solver's own starts used up the limit.
2. **Only the actual lineup limited, until a week-level solver.** The optimal lineup's
   totals and values are not limited. The limit-aware optimum is left to its own spec
   (#164).
3. **Keep the best starts.** Keep the per-day solver, and credit the optimal lineup's
   highest-valued starts in the period up to the limit. No slot is refilled, so this
   understates the optimum, and it still breaks R4.7 on a day.

## Decision

Chosen by the owner on 2026-10-18: **option 2**, with the week-level solver specified
separately (#164). Until then the optimal lineup is credited as the per-day solver
chose it, so the gap can include a start the league would not have credited (ADR 0073's
reason for limiting it). Across eight seasons that is 6 starts on 4 team-periods (spec
0152, C14).

## Consequences

- Good: the gap is never negative, and the actual lineup still reproduces the scored totals
  and the season values.
- Bad / accepted cost: on the team-periods where the optimal lineup goes over the limit,
  the gap overstates what was there to gain, by the starts the league would not have
  credited. `actual_pitcher_starts` and `optimal_pitcher_starts` still show such a period.
- Follow-ups: #164, a solver that chooses a matchup period's lineups together within the
  limit. When this ADR is accepted, 0073's `Status` becomes `superseded by` this ADR and
  0037's `amended by` points here.
