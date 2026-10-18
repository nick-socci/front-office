# 0080. A matchup's winner is who advanced, and a level playoff matchup goes to the higher seed

- Status: proposed
- Date: 2026-10-18
- Spec: [0159-playoff-tiebreak](../specs/0159-playoff-tiebreak/design.md) · Issue: #159

## Context

`fct_matchup_results.winner` has been the category result: more categories won is a win,
and equal is a tie. That is ESPN's rule in the regular season, where 47 level matchups are
ties on both sides (spec 0159, C5). In the playoffs ESPN never leaves a matchup tied. All
10 level playoff matchups of eight seasons went to the home side (C1), and those 10 are
most of what `fct_matchup_results_match_espn` fails on (C3). The settings say
`playoffMatchupTieRule: NONE` (C4), and ESPN's documented default for a tied playoff
matchup is that the higher seed advances (C12).

`rec_fantasy__category_wins_added.matchup_wins_added` rescores each matchup a player started
in and counts matchup wins "as `fct_matchup_results` has it", a level matchup as half a win.

## Decision drivers

- A reader of the mart sees the league's results, not ones the league never had.
- The category tie stays visible.
- Everything that counts matchup wins counts them the same way.

## Considered options

1. **`winner` is who advanced** — a level playoff matchup goes to the higher seed, a new
   column `is_decided_by_tiebreak` flags it, and a level regular-season matchup stays
   `TIE`.
2. **`winner` stays the category result** — a new column, `advancing_side`, says who
   advanced, and the reconciliation compares that column instead.

## Decision

Chosen by the owner on 2026-10-18: **option 1**. `winner` is the league's result, and a
reader who wants the category tie has the counts and `is_decided_by_tiebreak`. With
option 2, every reader that wants the result would have to know about a second column,
and one that didn't would be wrong in the playoffs only. The owner also chose that
`matchup_wins_added` follows the rule: in a playoff matchup, a level result, actual or
rescored, is a win for the home side and a loss for the away side.

## Consequences

- Good: the mart and ESPN agree on all 10 matchups. The standings and the rescoring check
  count a playoff matchup as the league did.
- Bad / accepted cost: `winner` no longer follows from the category counts alone. A
  reader must know that `is_decided_by_tiebreak` exists.
- Follow-ups: a league with a tie rule other than `NONE` fails the build (ADR 0082); how
  the higher seed is found is ADR 0081.
