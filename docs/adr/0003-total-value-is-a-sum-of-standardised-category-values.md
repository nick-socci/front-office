# 0003. Total value is a sum of standardised category values

- Status: proposed
- Date: 2026-10-03
- Spec: [0011-player-value](../specs/0011-player-value/design.md) · Issue: #11

## Context

The league scores 17 categories in different units. Ranking players, adds and drops needs
one number. Milestone 11 (#12) needs a scalar for the same reason and planned a sum of
z-scores.

## Decision drivers

- One method for milestones 10 and 11, stated once.
- No tunable weights to argue over or overfit.
- The per-category detail must remain available to anyone who rejects the sum.

## Considered options

1. **Equal-weight sum of standardised values** — each category's value over replacement
   divided by that category's standard deviation, summed.
2. **Per-category values only** — no scalar.
3. **Win-probability weighting** — weight each category by how often a unit of it flipped
   a matchup category in 2026.

## Decision

Chosen: **the equal-weight sum**. `standardised_value = value_over_replacement / sd`, where
`sd` is the population standard deviation of that category's value across (player, team)
pairs with a played day on the category's side; `total_value` is the sum over scored
categories. No mean is subtracted: replacement is already the zero point.

Win-probability weights are the better answer in principle, but they would be fitted on
143 matchups of one season and need their own validation; that is a milestone, not a
column.

## Consequences

- Good: no parameters; the scale is "standard deviations above a free agent, summed
  across categories".
- Bad / accepted cost: it treats all 17 categories as equally valuable and independent.
  A head-to-head manager does not: correlated categories (H, TB, R) are in effect
  counted several times, and a category already won by a mile is worth nothing more.
- Bad / accepted cost: the scale is relative to this league and season; totals are not
  comparable across seasons.
- Follow-ups: milestone 11 references this ADR for its scalar rather than defining
  another.
