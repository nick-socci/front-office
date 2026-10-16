# 0072. A start past the limit is zeroed at the credited grain

- Status: proposed
- Date: 2026-10-16
- Spec: [0152-games-started-limit](../specs/0152-games-started-limit/design.md) · Issue: #152

## Context

`int_fantasy__started_player_days` is one row per started player-day with the production
his slot credits (#10): batting for a hitter slot, pitching for a pitcher slot. Five
models sum it into what a team or player is credited with: matchup totals, player
category value, player season value, transaction impact, and category wins added. A
sixth, the player-day reconciliation, compares it with ESPN's per-player game lines.

ADR 0071 adds a rule: a start past the league's games-started limit is not credited.
ESPN's player-level game line for such a day still holds the start; only ESPN's side
total leaves it out (spec 0152, C12).

## Decision drivers

- Every sum of credited production is right without each reader having to remember the
  rule.
- No row disappears: a started player-day that scored nothing is still a started day.
- The player-day reconciliation still compares like with like.

## Considered options

1. **At the credited grain** — the row stays, marked `is_over_start_limit`, with its
   pitching components zero; the player-day reconciliation leaves marked rows out.
2. **A flag only** — the components stay; each of the five summing models filters on it.
3. **A new model** between the started days and their readers, holding what counts.

## Decision

Chosen by the owner on 2026-10-16, as recommended, with every pitching column zeroed:
**option 1**, because the model already means "what ESPN credits for this
player-day", and the limit is part of that rule. The five summing models are right by
construction. Option 2 leaves five places to forget a filter, each wrong with no test to
say so. Option 3 moves the grain six models and six singular tests read, for a rule that
binds once in eight seasons.

Every pitching column of the marked row is zero, `games_pitched` and `games_started`
included. The marts count a played started day by `games_pitched` (spec 0152, C17), so the
day is not a played started day either: value per played day (ADR 0002) is not diluted by
a day the league did not count, and transaction impact counts it the same way. `played`
and `input_status` still describe the player's whole day, as they do for slot-role
crediting (#10). Keeping `games_pitched` instead would count a played day that scored
nothing.

The player-day reconciliation compares ESPN's game line with ours only for rows not
marked: for a marked row ESPN's line holds the start by design, and the side-level
comparison already sees that ESPN's total does not.

## Consequences

- Good: matchup totals, player value and transaction impact follow with no change of
  their own.
- Good: `is_over_start_limit` says, on the row, why a start scored nothing.
- Bad / accepted cost: the player's season value has one played started day fewer than
  the days he appeared on the mound in a pitcher slot.
- Bad / accepted cost: for a marked row, `int_fantasy__started_player_days` no longer
  equals ESPN's player-level line, and the one reconciliation that compares them has to
  know it.
- Follow-ups: none.
