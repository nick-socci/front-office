# Total value scaled by the matchup margin — requirements

Issue: #55 · Tier: M · Status: draft

## Problem

`total_value` is the equal-weight sum of each category's value over replacement divided by
that category's standard deviation across (player, team) pairs
([ADR 0003](../../adr/0003-total-value-is-a-sum-of-standardised-category-values.md)). After
#52, starters hold 15 of the top 20 values and the two best pairs in the league are
starters; the owner's eye test did not accept that as settled (#55).

Grounding shows the cause is the denominator, not the pitchers. A spread across players
says how unusual a player is, not what his production is worth in a matchup. Measured
against how far apart two teams actually finish in a matchup, one player-standard
deviation is worth very different amounts by category: 0.54 of a matchup margin for
innings, 0.80 for wins and losses, and 2.01 for stolen bases, 1.81 for batter strikeouts,
1.60 for walks. Equal weights therefore pay double for the categories starters fill and
half for several that hitters fill (evidence in [design.md](design.md#evidence)).

## Goals

- A category value is expressed in the unit a head-to-head categories league is decided
  in: how far it moves a matchup's margin in that category.
- The summary number compares a hitter, a starter and a reliever on that one scale.
- Nothing upstream of the standardisation changes.

## No-gos

- **No change to value over replacement**: replacement levels, pools, the per-played-day
  unit (ADRs 0001, 0002, 0008, 0009) and every `numerator`, `denominator`,
  `played_days`, `contribution` and `value_over_replacement` stay bit for bit.
- **No fitted or tunable weights**, and no target for the starter–hitter split. The scale
  is measured, and whatever ranking follows is reported.
- **No "category wins added" column.** Converting margins to win probability needs a
  model of each category's margin distribution; the linear approximation is visibly rough
  on 2026 (design.md). Not shipped.
- **No correction for correlated categories** (H, TB, R). Each is its own category in the
  league's scoring.
- **No change to grains, row counts, windows or column names.**
- **No lineup work.** #12 consumes whatever scalar this leaves.
- **No tolerance widening** and no test weakened to make a build pass.

## Rabbit holes

- *Chasing a validation that 12 teams cannot give* → the team-level check is reported with
  its sample size, and the case for the scale is that it is the right unit, not that it
  fits better.
- *Per-week scales, or dropping the two long matchup periods* → one scale per category
  from every matchup; the sensitivity to the two long periods is reported and that is all.
- *Fitting each category's margin distribution* → see the no-go on wins added.

## Requirements

### R1. Category scales

- R1.1 THE SYSTEM SHALL provide `int_fantasy__category_scales` with one row per scored
  category of a league-season, holding the number of matchups measured, the margin scale
  and, for a rate category, the typical side denominator.
- R1.2 THE SYSTEM SHALL compute the margin scale as the root mean square of the difference
  between the two sides' category values over every matchup in which both are defined, so
  that it does not depend on which side is called home.
- R1.3 THE SYSTEM SHALL compute the typical side denominator as the mean of the category's
  denominator over matchup sides whose rate is defined (a non-null value, so a
  denominator above zero), and leave it null for a count category.
- R1.4 THE SYSTEM SHALL take the category list from `int_fantasy__categories` and the side
  values from `int_fantasy__matchup_stat_values`; no category or count of categories is
  hardcoded.
- R1.5 IF a category has no matchup with both sides defined THEN THE SYSTEM SHALL still
  produce its row, with a null margin scale.

### R2. Player value

- R2.1 THE SYSTEM SHALL compute `standardised_value` as value over replacement divided by
  the margin scale for a count category, and as value over replacement divided by the
  typical side denominator and then by the margin scale for a rate category.
- R2.2 WHEN a pair has no played day on a category's side THE SYSTEM SHALL give
  `standardised_value` as 0.
- R2.3 IF the margin scale is zero or null, or a rate's typical side denominator is zero
  or null, THEN THE SYSTEM SHALL give `standardised_value` as 0, and null only when value
  over replacement is itself null.
- R2.4 THE SYSTEM SHALL keep `total_value` as the sum of standardised values over the
  scored categories, null if any is null.
- R2.5 THE SYSTEM SHALL leave `numerator`, `denominator`, `played_days`, `contribution`
  and `value_over_replacement` of `fct_player_category_value` identical to their values
  before the change.

### R3. Transaction impact

- R3.1 THE SYSTEM SHALL standardise a transaction window's category values with the same
  scales, read from `int_fantasy__category_scales`.
- R3.2 THE SYSTEM SHALL keep an add whose window covers a pair's whole season equal to
  that pair's season total.

### R4. The record

- R4.1 THE SYSTEM SHALL state in the scale model's header what the scale is, how a rate is
  converted, its sample size, its sensitivity to the two long matchup periods, and that
  it is measured from the same season's matchups (so it moves on a restatement, includes
  the players it measures, and is noisy early in a season).
- R4.2 THE SYSTEM SHALL record that the denominator of ADR 0003 is superseded, in ADR
  0003, the ADR index and #12.

## Expected values

2026 season, `data/warehouse.duckdb` as of 2026-10-03 (after #54), measured read-only.

| Check | Expected | How to verify |
|---|---|---|
| Row counts | `fct_player_season_value` 580, `fct_player_category_value` 9,860, `fct_transaction_impact` 737: unchanged | row counts |
| `int_fantasy__category_scales` rows | 17, each over 143 matchups | row count; unique on category |
| Margin scales, counts | H 12.7811, HR 4.1010, TB 22.8409, B_BB 8.3971, R 8.4779, RBI 9.9111, SB 3.6201, B_SO 12.3936, IP 47.1749 outs, K 20.3186, W 2.6391, L 2.4947, SV+HD 3.5988 | query |
| Margin scales, rates | AVG 0.0450, WHIP 0.2653, ERA 1.6371, K/9 1.9590 | query |
| Typical side denominators | 207.83 at-bats (AVG); 172.40 outs (WHIP, ERA, K/9) | query |
| Value over replacement | all 9,860 rows bit-identical in `numerator`, `denominator`, `played_days`, `contribution`, `value_over_replacement` | compare with the pre-build snapshot |
| Median `total_value` by `replacement_group` | hitter +1.32 (was +0.78), SP +1.56 (+1.52), RP +0.89 (+0.67) | query |
| Top 20 | 10 starters, 10 hitters, 0 relievers (was 15 / 5 / 0) | query |
| Top 50 / top 100 | SP 19 / 37, hitter 28 / 54, RP 3 / 9 | query |
| Bottom 20 | hitter 17, SP 2, RP 1 | query |
| Relievers below zero | 36 of 107 `RP` pairs | query |
| Sum of standardised values | batting categories 1,139, pitching 1,250 (were 862 and 1,152) | query |
| Rank agreement with today | rank correlation of `total_value` 0.992 | compare with the snapshot |
| Transaction impact, sums of `total_value` | hitter adds 221.09 (151), pitcher adds 457.47 (223), hitter drops 170.37 (153), pitcher drops 451.72 (210) | query |
| Transaction impact, other columns | all 737 rows identical outside `total_value` | compare with the pre-build snapshot |
| Eye test | top and bottom 20 read by the owner | recorded on #55 |
