# 0073. Both lineups' totals and values are credited under the limit, and the solver still ignores it

- Status: superseded by [0079](0079-only-the-actual-lineup-is-credited-under-the-limit-until-the-optimal-one-is-solved-a-week-at-a-time.md)
- Date: 2026-10-16
- Spec: [0152-games-started-limit](../specs/0152-games-started-limit/design.md) · Issue: #152
- Amends: [0037](0037-the-optimal-lineup-replaces-a-played-starter-only-with-a-player-who-played.md), for how the lineups' totals and values are credited

## Context

ADR 0037 chose the hindsight-optimal lineup by solving each team-day alone, and did not
enforce the league's starts limit: enforcing it would couple a week's days into one
problem for the few team-periods where it binds. It also left the limit uninterpreted in
the lineup totals.

`int_fantasy__lineup_category_totals` credits each lineup's players from their MLB lines,
and a test holds the actual lineup's totals exactly equal to the scored totals. Once the
scored totals apply the limit (ADRs 0071, 0072), the actual lineup's totals must apply it
too, or that test fails on the one side where it binds (spec 0152, C13). The same holds
for the lineup values: `fct_lineup_decisions.actual_value` is a sum of day values, and the
day values add back to the season values (C18). So the actual lineup is limited either
way, and the question is the optimal lineup's totals and value. The day values the solver
reads stay unlimited: a day value is what the day was worth. Across eight seasons the
optimal lineups exceed the limit in 22 of 2,052 team-periods, and the rule would leave 6
of their starts uncredited, on 4 team-periods (C14).

## Decision drivers

- Both lineups are scored by the rules the league scores by, so the gap between them
  counts only what would have counted.
- The solver stays a per-day problem (ADR 0037's reason still holds).

## Considered options

1. **Both lineups' totals and values credited under the limit** — each lineup counts its
   own starts toward the limit; the solver and its inputs are unchanged.
2. **Only the actual lineup's** — the optimal lineup's totals and value are not limited.

## Decision

Chosen by the owner on 2026-10-16, as recommended: **option 1**, because a gap measured
between a limited actual total and an unlimited optimal one counts starts the league
would not have credited. The solver still
chooses each team-day alone: it can pick a start that then scores nothing, which is the
accepted cost of ADR 0037's per-day solve, now visible in the totals instead of hidden
in them.

## Consequences

- Good: the actual and optimal totals are comparable on every team-period; a league with
  a tight limit is not misread.
- Bad / accepted cost: on the 4 team-periods of C14 the optimal lineup is no longer
  optimal under the rule that scores it; a solver that knew the limit could do better.
- Follow-ups: when this is accepted, 0037's `Status` gains `amended by` this ADR.
