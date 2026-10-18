# 0078. A winner that flips only through explained category results is explained

- Status: proposed
- Date: 2026-10-16
- Spec: [0147-espn-matchup-lines](../specs/0147-espn-matchup-lines/design.md) · Issue: #147

## Context

`fct_matchup_results_match_espn` fails on any winner that differs. Its comment says why:
no 2026 residual flipped one, and a future flip deserves a person's attention. Seven past
seasons give 15 differing winners. Ten are tied playoff matchups, a rule of their own
(#159). The other five flip only because category results flip, and each of those
results is `explained` (three today, two once spec 0147's values are; C15).

## Decision drivers

- A finding should be raised once, where its cause is.
- A winner that differs with no differing category behind it must still fail.

## Considered options

1. **Explained when every differing category is**: a winner that differs is not
   returned when the matchup has at least one differing category result and all of them
   are `explained`.
2. **A register of winners**, by hand.
3. **Keep failing** on every differing winner.

## Decision

Chosen by the owner on 2026-10-16: **option 1**. The rule lives in a view, `rec_espn__winner_differences`,
which a unit test holds and the test selects from.

## Consequences

- Good: the 5 winners stop failing. Their causes are already shown and explained one
  level down.
- Good: a winner differing on level categories (#159's) or through an unexplained result
  still fails.
- Bad / accepted cost: a person is no longer told when a residual flips a winner. The
  view lists every such matchup for anyone who asks.
