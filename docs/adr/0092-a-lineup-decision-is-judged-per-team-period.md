# 0092. A lineup decision is judged per team-period

- Status: proposed
- Date: 2026-10-21
- Spec: [0164-optimal-lineup-per-matchup-period](../specs/0164-optimal-lineup-per-matchup-period/design.md) · Issue: #164

## Context

Spec 0012 tests two rules per team-day:
- **R4.7:** the gap is never below zero, and no role has fewer assigned players than
  played starters.
- **R4.8:** a team-day with no gain has no player brought in, sat or moved.

Under ADR 0090 the days of a period are chosen together, so a day may give up value for a
later one. On real data no team-day's gap is negative (spec 0164, C9), but nothing
guarantees it.

The days also share a cap on starts. On a day with an unknown option value (unvalued,
R3.5) the optimum cannot be chosen, so neither can its starts, nor the cap left for the
other days. No team-day is unvalued in eight seasons (C5).

## Decision drivers

- A test that fails says something is wrong, not that the solver did its job.
- No value is guessed.

## Considered options

For R4.7 and R4.8:
1. **Per team-period.** The period's summed gap is at least zero, and a period with no gain
   changes nothing on any day. The role minimum stays per day.
2. **Per team-day, as today.**
3. **Per team-period, plus a warning on a negative team-day.**

For an unvalued day:
4. **The whole team-period is unvalued.**
5. **Solve the other days**, counting the unvalued day as having no starts.

## Decision

Chosen by the owner on 2026-10-21, as recommended: **1 and 4**.

- **1 over 2:** option 2 can fail the build on a correct optimum.
- **1 over 3:** option 3 warns on correct behaviour.
- **4 over 5:** option 5 guesses the starts that count toward the period's cap. The
  category mart already blanks a side's optimal totals when any day of its period is
  unvalued (spec 0012, R5.4).

## Consequences

- Good: both tests hold by construction and still catch a wrong matrix or a wrong sum.
- Good: no team-period is solved on a guess.
- Bad / accepted cost: a negative day can appear unflagged. `fct_lineup_decisions` shows
  it, and the period shows why.
- Bad / accepted cost: one unvalued day blanks its whole period's optimal values. It has
  not happened in eight seasons.
- Follow-ups: none.
