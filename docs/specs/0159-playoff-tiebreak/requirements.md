# A tied playoff matchup goes to the higher seed — requirements

Issue: #159 · Tier: M · Status: draft

## Problem

`fct_matchup_results.winner` is the category result: equal category wins is `TIE`. In
the playoffs ESPN never leaves a matchup tied. All 10 playoff matchups in eight seasons
whose categories are level (8–8) have ESPN's `winner` = `HOME` (design.md, C1), and they
are 10 of the 16 rows `fct_matchup_results_match_espn` fails on (C3). Every season's
settings say `playoffMatchupTieRule: NONE` (C4), and ESPN's documented default for a tied
playoff matchup is that the higher seed advances. ESPN seats the higher seed at home in
every one of the 136 playoff matchups (C2). So our mart reports a result the league never
had, and the standings and the rescoring check built on it count those matchups as half a
win each.

The owner decided on 2026-10-18 that `winner` means who advanced; that the model finds the
higher seed as the home side, with a test that holds home to the better seed; and that
`rec_fantasy__category_wins_added.matchup_wins_added` follows the same rule.

## Goals

- `winner` is the league's result: a level playoff matchup goes to the higher seed, and a
  level regular-season matchup stays a tie.
- A playoff win decided by the tiebreak can be told apart from one won on categories.
- The rule is held, not assumed: the DuckDB build fails if ESPN seats a lower seed at home
  (on BigQuery once #136 brings the teams endpoint there), and every build fails if a
  league-season sets a tie rule the models do not know.
- `fct_matchup_results_match_espn` fails only on #160's rows, and nothing else that
  matches ESPN changes.

## No-gos

Explicitly out of scope. Work that drifts here is escalated, not done.

- No seeding is computed. ESPN's `playoffSeed` is read only by the test that holds home to
  the better seed (R2.4); the model does not read seeds.
- No tie rule other than `NONE` is modelled, for the playoffs or the regular season. One
  fails the build instead (R1.2); what it means is settled when a league sets one.
- The regular season is unchanged: a level regular-season matchup is `TIE`.
- #160 (the minimum innings) and #161 (the 2023 slope) are not touched; their rows keep
  failing until they land.
- `category_wins_added`, and so every slope of `rec_fantasy__category_wins_by_group`, is
  not changed: a matchup tiebreak cannot change a category result.
- No new landing and no new ESPN request.

## Rabbit holes

Places this could sink time, and the decision already taken to avoid them.

- What ESPN's other `playoffMatchupTieRule` values do, and what `playoffMatchupTieRuleBy`
  names → not researched: every covered league-season is `NONE`, and any other value fails
  the build by name (ADR 0082).
- When a seed is "higher" (seeding rules, division winners, ties in the standings) → not
  modelled: ESPN's own `playoffSeed` decides it, and ESPN seats the better seed at home
  (C2). The model reads only the side (ADR 0081).
- `stg_espn__teams` in the BigQuery slice → avoided: the teams endpoint holds member data
  and its path to BigQuery is undecided (#136). Only the guard test reads it, and the
  slice's cautious selection leaves that test out (C9).

## Requirements

### R1. The league's tie rules are read and understood

- R1.1 THE SYSTEM SHALL hold, in `stg_espn__league_settings`, each league-season's
  `scoringSettings.playoffMatchupTieRule` as `playoff_matchup_tie_rule` and
  `scoringSettings.matchupTieRule` as `matchup_tie_rule`, as ESPN gives them.
- R1.2 IF a league-season with rosters (ADR 0026) has a `playoff_matchup_tie_rule` or a
  `matchup_tie_rule` that is not `NONE`, or has none, THEN THE SYSTEM SHALL fail the
  build, naming the league-season and both values.

### R2. A level playoff matchup goes to the higher seed

- R2.1 WHEN a playoff matchup (`playoff_tier` other than `NONE`) has every category
  decided and equal category wins THE SYSTEM SHALL give it `winner` = `HOME` and
  `is_decided_by_tiebreak` = true (ADRs 0080, 0081).
- R2.2 THE SYSTEM SHALL give a level regular-season matchup `winner` = `TIE`, as today.
- R2.3 THE SYSTEM SHALL give `is_decided_by_tiebreak` = false to every matchup that R2.1
  does not decide, including one whose `winner` is null because a category is undecided.
- R2.4 IF a playoff matchup of a league-season with rosters has a home team whose
  `playoff_seed` is not better (lower) than the away team's, or either team has no seed,
  THEN THE SYSTEM SHALL fail the build, naming the matchup and both seeds (ADR 0081).
- R2.5 THE SYSTEM SHALL keep `fct_matchup_results` in the BigQuery slice, reading nothing
  outside it.

### R3. The rescoring check counts matchups the same way

- R3.1 THE SYSTEM SHALL count, in `rec_fantasy__category_wins_added.matchup_wins_added`, a
  playoff matchup whose categories are level, actual or rescored, as a win (1) for the
  home side and a loss (0) for the away side; a level regular-season matchup stays half a
  win (0.5) (ADR 0080).
- R3.2 THE SYSTEM SHALL leave `category_wins_added` unchanged.

## Expected values

Counted on `data/warehouse_147.duckdb` (eight seasons, `main` with #147 and #152) on
2026-10-18; recounted at build time.

| Check | Expected | How to verify |
|---|---|---|
| Tie rules (R1.1) | `NONE` and `NONE` in all eight covered league-seasons (and 2020, not covered) | the staged columns |
| R1.2 on the real data | passes | the singular test |
| Home is the better seed (R2.4) | 136 of 136 playoff matchups; the test passes | the singular test |
| `fct_matchup_results` rows | unchanged in number | count before and after |
| `winner` changes | exactly 10 rows, `TIE` → `HOME`: 2018 m133, m139; 2019 m143; 2021 m132; 2022 m131, m136; 2024 m145, m155; 2025 m138, m139 | compare with the saved table |
| `is_decided_by_tiebreak` | true on those 10, false on every other row | count |
| Regular-season ties (R2.2) | 47 `TIE`, unchanged | count |
| `fct_matchup_results_match_espn` | 16 → 6 (2021 m113, #160) | the test |
| `rec_espn__winner_differences` | 15 rows → 5, all explained (`problem` null) | the view |
| `category_wins_added` (R3.2) | every pair unchanged; `rec_fantasy__category_wins_by_group` unchanged; `values_track_rescored_category_wins` 1, the same row (#161) | compare with the saved tables |
| `matchup_wins_added` (R3.1) | changes only on pairs with a started day in a playoff matchup (2,090 of 4,239 pairs): a rescored draw can level any playoff matchup, not only the 10; every pair with no playoff started day unchanged | compare with the saved table |
| Every other relation | identical, apart from the new columns | `scripts/compare_warehouses.py` |
