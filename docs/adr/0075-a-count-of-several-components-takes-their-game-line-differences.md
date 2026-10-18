# 0075. A count of several components takes the sum of their game-line differences

- Status: accepted
- Date: 2026-10-16
- Spec: [0147-espn-matchup-lines](../specs/0147-espn-matchup-lines/design.md) · Issue: #147

## Context

ADR 0064 gives a count a game-line difference from the player-day differences of its
stat. Those are compared only for stats that are exactly one component, so SVHD (saves
plus holds) never has one. Two past-season SVHD values are `unexplained` although their
save is `explained_by_game_lines` on the same side (spec 0147, C9). 2026's register holds
one SVHD row by hand for the same reason ("follows from JoJo Romero's hold").

## Decision drivers

- A count's difference that follows from its components' traced differences is as traced
  as theirs.
- Use the rules in `int_fantasy__stat_components`, not stat ids.

## Considered options

1. **Sum the components' game-line differences** for a count with more than one
   component.
2. **Register such values by hand**, as 2026's was.

## Decision

Chosen by the owner on 2026-10-16: **option 1**. A count with more than one component, all numerators of
weight 1, takes as its game-line difference the sum of its components' single-stat
game-line differences. A single-component count is unchanged.

## Consequences

- Good: the 2 SVHD values are explained, and so is any future count of this kind.
- Bad / accepted cost: none found. 2026's hand row still matches and stays.
