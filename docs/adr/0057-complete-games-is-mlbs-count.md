# 0057. Complete games is MLB's count, credited like every pitching component

- Status: proposed
- Date: 2026-10-11
- Spec: [0083-past-season-rosters](../specs/0083-past-season-rosters/design.md) · Issue: #83

## Context

The league scored complete games (ESPN stat 62) in 2018, 2019 and 2021, and it is the
only stat ESPN reports for a matchup side that has no component rule (spec 0083, C13).
ADR 0026 let those seasons build without one while they had no rosters. ESPN's totals
are 33, 29 and 37 complete games a season across all sides (C14). MLB's boxscore gives
`completeGames` per pitcher; it is already staged and summed per player-day, and is not
yet a component (C15).

## Decision drivers

- Components, never rates, and from the source of record.
- What ESPN's stat means is the owner's to decide, and the totals can check it.
- No rule of our own where MLB publishes the number.

## Considered options

1. **MLB's `completeGames`**, summed, as a new component `complete_games`.
2. **Derived**: a starter who recorded every out his team recorded in the game.
3. **No rule**: complete games stays uncomputed.

## Decision

Chosen by the owner on 2026-10-11, going through the spec's decisions: **option 1**. ESPN stat 62 is the sum of `complete_games` over a team's
started pitcher-days, by the rule every pitching component follows.

Option 2 needs its own answer for shortened games and a per-game team total that is
not staged. Option 3 leaves three seasons failing the test that every scored category
has a rule.

## Consequences

- Good: one seed row and one name in the component list.
- Bad / accepted cost: where MLB and ESPN credit a shortened game differently, most
  likely the seven-inning doubleheaders of 2021, the difference appears in the
  reconciliation and is settled there, in the register or by a new ADR.
