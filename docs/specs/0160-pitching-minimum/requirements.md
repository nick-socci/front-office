# A side below the league's pitching minimum loses its ratio categories — requirements

Issue: #160 · Tier: M · Status: draft

## Problem

From 2021 on, every season's settings hold a pitching minimum,
`scoringSettings.statQualificationMinimum: {"statId": 34, "limitValue": 30.0}`: 30 outs (10
innings) a matchup (design.md, C1). The models do not apply it. In eight seasons one side
fell below it: 2021, matchup 113, team 5, with 24 outs (C2). ESPN gave team 5 a loss in
WHIP, K/9 and L, which by value it won, while its 0–0 tie in CG stayed a tie (C3). Those 3
categories on both sides are the 6 category results `fct_matchup_results_match_espn` fails
on that no other spec explains (C4). A league that sets a tighter minimum, or a team that
punts pitching, would have its category results misread with no test saying so.

ESPN's help pages do not document the rule (C11). The owner decided on 2026-10-18, from the
one case:
- a side below the minimum loses its pitching categories that are rates or where lower is
  better;
- when both sides are below it, those categories are ties;
- every place that decides a category result applies the minimum.

## Goals

- A category result follows the league's minimum wherever the models decide one: the
  actual results, the optimal lineup's, and the rescoring check's.
- The minimum is read from each league-season's settings. A league-season with none is
  unchanged, and one the models cannot read fails the build by name.
- `fct_matchup_results_match_espn` loses its 6 rows of 2021 m113, and nothing else that
  matches ESPN changes.

## No-gos

Explicitly out of scope. Work that drifts here is escalated, not done.

- No other qualification stat. A minimum on any stat but outs (34) fails the build (R1.2).
- No scaling by period length. The minimum applies per matchup as given: no long period
  in six seasons has a side below 30 outs scaled to its length (C6), so the choice changes
  no result. It is recorded as an open question.
- Rotisserie is not modelled. 2020's minimum (3,000 outs, a season total) is in a
  rotisserie season that is not covered (ADR 0026), and a covered rotisserie league-season
  with a minimum fails the build (R1.2).
- Player value is untouched: `fct_player_category_value` and `fct_player_season_value` are
  built from margins, not category results.
- #159 (the playoff tiebreak) and #161 (the 2023 slope) are not touched.
- No new landing and no new ESPN request.

## Rabbit holes

Places this could sink time, and the decision already taken to avoid them.

- What ESPN does when both sides fall short → not observed. The owner chose a tie
  (ADR 0083), and the reconciliation will show a difference if ESPN ever disagrees.
- Which categories a "pitching" category is → decided from the components, not from stat
  ids. A category whose components are all pitching columns, and which is a rate (it has a
  denominator) or lower-is-better, is bound by the minimum (C5). Nothing names WHIP or ERA.
- The scoring rule lives in three models → one macro, used by all three (ADR 0084), so the
  copies cannot drift.

## Requirements

### R1. The minimum is read and understood

- R1.1 THE SYSTEM SHALL hold, per league-season, the `statQualificationMinimum` of its
  newest settings capture: the `statId` as `qualification_stat_id` and the `limitValue` as
  `qualification_minimum`, null when the settings have none, as ESPN gives them.
- R1.2 IF a league-season with rosters (ADR 0026) has a minimum whose stat is not 34
  (outs) or cannot be read, a stat with no minimum, or any minimum while its scoring type
  is not known to be head-to-head, THEN THE SYSTEM SHALL fail the build, naming the
  league-season and the setting (ADR 0085).
- R1.3 THE SYSTEM SHALL give `int_fantasy__league_seasons` a `pitching_minimum_outs`: the
  `qualification_minimum` when the stat is 34, and null when the league-season sets none.

### R2. A category bound by the minimum

- R2.1 THE SYSTEM SHALL mark a scored category as bound by the minimum when every one of
  its components is a pitching component and it is a rate (it has a denominator part) or
  lower-is-better.
- R2.2 WHEN a side's outs in a matchup are below the league-season's `pitching_minimum_outs`
  and its opponent's are not THE SYSTEM SHALL give that side a `LOSS`, and its opponent a
  `WIN`, in every bound category, whatever the values (ADR 0083).
- R2.3 WHEN both sides are below the minimum THE SYSTEM SHALL give both a `TIE` in every
  bound category (ADR 0083).
- R2.4 THE SYSTEM SHALL decide every category that is not bound, and every category of a
  matchup where neither side is below the minimum or the league-season sets none, as
  today.
- R2.5 THE SYSTEM SHALL apply R2.2 and R2.3 before the rule that gives a null result for a
  null value: a side below the minimum loses a bound category even when its rate is
  undefined (no outs at all).

### R3. Every place that decides a category result applies it

- R3.1 THE SYSTEM SHALL decide `fct_matchup_category_scores.result`, and so
  `fct_matchup_results`, by R2, with each side's actual outs, and carry
  `is_below_minimum` (the team's side) and `is_opponent_below_minimum` on every row.
- R3.2 THE SYSTEM SHALL decide `fct_lineup_decision_categories.optimal_result` by R2, with
  the optimal lineup's own outs for the team and the opponent's actual outs; its actual
  result is the fact's, as today.
- R3.3 THE SYSTEM SHALL decide the actual and the rescored results in
  `rec_fantasy__category_wins_added` by R2, the rescored side judged on its swapped outs.
- R3.4 THE SYSTEM SHALL decide a result by one macro in all three models (ADR 0084).
- R3.5 THE SYSTEM SHALL keep the models of the BigQuery slice in it, reading nothing
  outside it.

## Expected values

Counted on `data/warehouse_147.duckdb` (eight seasons, `main` with #147 and #152) on
2026-10-18; recounted at build time.

| Check | Expected | How to verify |
|---|---|---|
| `pitching_minimum_outs` (R1.3) | 30 in 2021 to 2026; null in 2018 and 2019; 3,000 in 2020 (rotisserie, no rosters, so no model applies it) | the column |
| R1.2 on the real data | passes (2020 is rotisserie and not covered) | the singular test |
| Bound categories (R2.1) | WHIP, ERA, K/9 and L in every season from 2021; no batting category (not B_SO) | the marked categories |
| Sides below the minimum | 1: 2021, m113, team 5 (24 outs) | `is_below_minimum` |
| `fct_matchup_category_scores` results | exactly 6 change: team 5's WHIP, K/9 and L `WIN` → `LOSS`, team 8's `LOSS` → `WIN`; ERA (already a loss) and CG (`TIE`, not bound) unchanged | compare with the saved table |
| `fct_matchup_results` | 2021 m113 only: home (5) category wins 6 → 3, away (8) 11 → 14, ties 1; winner `AWAY` unchanged; ESPN's 3–14–1 | compare |
| `rec_espn__category_result_differences` | `unexplained` 6 → 0 | count by status |
| `fct_matchup_results_match_espn` | 16 → 10 without #159; 6 → 0 once #159 has landed | the test |
| `fct_lineup_decision_categories` | `actual_result` moves on the 6 rows above; `optimal_result` moves only on 2021 m113 rows (team 5's optimal lineup has 27 outs, also below) | compare |
| `rec_fantasy__category_wins_added` | moves only on pairs with a started day in 2021 m113 (41) or whose side less their own outs is below 30 (8 pairs): at most 49 of 3,277 pairs from 2021 on | compare |
| `values_track_rescored_category_wins` | 1 failing row, the same (#161) | the test |
| `rec_fantasy__category_wins_by_group` | may move in 2021 to 2026 only, by what the pairs above carry; 2018 and 2019 unchanged | compare |
| Every other relation | identical, apart from the new columns | `scripts/compare_warehouses.py` |
