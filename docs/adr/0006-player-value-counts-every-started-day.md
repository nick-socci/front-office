# 0006. Player value counts every started day

- Status: proposed
- Date: 2026-10-03
- Spec: [0011-player-value](../specs/0011-player-value/design.md) · Issue: #11

## Context

The issue's test is that players' contributions sum to their team's season totals from
#10. But #10's totals are per matchup side, and 245 started player-days belong to no
matchup: two teams, 2026-08-31 to 09-06, by the look of it first-round playoff byes.
38,420 started days are inside matchups; 38,665 exist.

## Decision drivers

- The reconciliation must be exact, with no tolerance.
- A player's season should not lose a week because his team earned a bye.
- Days that scored nothing in a matchup must be visible as such.

## Considered options

1. **Value counts every started day; reconciliation is scoped to matchup days**, and
   `started_days_outside_matchups` is reported.
2. **Value counts matchup days only.** One population for both.
3. **Two sets of columns**, matchup-only and all days.

## Decision

Chosen: **option 1**. Value describes the player; the reconciliation proves the
arithmetic where #10 gives something to prove it against. A second test proves that
inside plus outside equals every started day, so no day is in neither.

Option 2 undercounts the two best regular-season teams' players. Option 3 doubles the
columns of the long fact for 0.6% of days.

## Consequences

- Good: player seasons are complete; the reconciliation stays exact.
- Bad / accepted cost: a player's value includes production that affected no matchup.
  The count is on every row.
- Follow-ups: confirm with the person that the 245 days are byes (matchup data shows no
  side for those teams that week; the cause is inferred).
