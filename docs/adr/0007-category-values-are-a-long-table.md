# 0007. Category values are a long table

- Status: proposed
- Date: 2026-10-03
- Spec: [0011-player-value](../specs/0011-player-value/design.md) · Issue: #11

## Context

The issue names one model, `fct_player_season_value`, holding day counts, per-category
contributions, rates and value. The project's rule since #10 is that nothing in SQL knows
which or how many categories the league scores: `fct_matchup_category_scores` is one row
per (matchup, team, category).

## Decision drivers

- A different league must be a different seed, not different SQL.
- One grain per table.
- Consistency with `fct_matchup_category_scores`.

## Considered options

1. **Two facts**: `fct_player_category_value` at (player, team, category) and
   `fct_player_season_value` at (player, team).
2. **One wide fact** with a column set per category (51 or more generated columns).
3. **One long fact** with day counts and total value repeated on each category row.

## Decision

Chosen: **two facts**. The long one carries contribution, value over replacement and
standardised value; the narrow one carries day counts and `total_value`.

Option 2 either hardcodes the categories or generates column names from data, which a
contract cannot describe. Option 3 mixes two grains, so summing `started_days` gives 17
times the truth.

## Consequences

- Good: rules-driven; each table sums safely.
- Bad / accepted cost: four marts where the issue listed three, and a join to read a
  player's categories beside his day counts.
- Follow-ups: none.
