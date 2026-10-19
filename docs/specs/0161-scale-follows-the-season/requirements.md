# A season's scale becomes its own as its matchups are played — requirements

Issue: #161 · Tier: L · Status: draft

## Problem

`values_track_rescored_category_wins` fails on one row. 2023 starting pitchers' slope is
0.3333, below the band's floor of 0.34 (spec 0089, R3.5). The issue was measured again
after #152 landed, as it asked: the slope moved down from 0.336 (design.md, C1).

On 2026-10-18 the owner decided to treat this as a real tilt in starters' values, to be
found and fixed, with the band left alone. Most of the 2023 tilt traces to the category
scale. ADR 0027 blends each category's scale from the league's earlier seasons, counted
as 100 matchups, and the season's own matchups. In a completed season of 126 matchups,
history still carries 44% of the weight (C4). 2023 was MLB's first season under the pitch
clock. In six of its seven pitching categories, 2023's own margins were wider than the
blend allowed for (IP 61.6 outs against a history of 47.9; ERA 2.25 against 1.84). Those
blended scales came out 3% to 9% below 2023's own margins; K/9's came out 4% above (C3).
Starters' values were inflated by about as much.

Scored on the season's own matchups, 2023 starters' slope is 0.3474, inside the band
(C6). ADR 0027's own measurements say the season's own matchups are the better guide by
its end ("after sixteen periods the season is ahead, 11.5% against 12.7%"). Yet the scale
of a finished season still leans on seasons that are not it.

## Goals

- A category's scale estimates the margin of the season being valued. Early in a season
  it leans on history, as ADR 0027 intends. Once the season's matchups are all played, it
  is the season's own.
- `values_track_rescored_category_wins` passes on the eight seasons with its band and its
  judging rule unchanged.
- The rule stays general. It names no season, rule change or league, and it has no tuned
  weight. A new league, or a category with no history, is scaled as today.

## No-gos

Explicitly out of scope. Work that drifts here is escalated, not done.

- No change to `values_track_rescored_category_wins`: not to its band (0.34 to 0.47), its
  0.75 correlation threshold, or its 100-pair minimum.
- No change to the replacement levels. The start level is not the 2023 cause: its gap to
  the MLB average start is steady across seasons (C8).
- No change to which matchups a scale is measured from (ADR 0027's reported, decided,
  regular-season margins), or to the 100 prior matchups a category needs before it uses
  history.
- No declared list of seasons or rule changes (ADR 0027 rejected that as option 6).
- No change to 2018, or to any category that does not use history.
- The small tilt of starters across seasons is not chased here. Starters' slopes average
  0.385 under this rule; theory gives 0.40 (*Open questions*).

## Rabbit holes

Places this could sink time, and the decision already taken to avoid them.

- Re-deriving the band from measured noise → not done; the owner framed this as a tilt.
  For the record, the bootstrap SD of a season's starter slope is about 0.022 (C7).
- Tuning the history weight (25, 50) to pass 2023 → rejected. ADR 0027's drivers rule out
  a tuned weight, and 25 only just passes (0.342, C6).
- Proving the in-season behaviour against past in-season captures → not attempted. No
  in-season capture of a past season is landed. The rule is held at its two ends by unit
  tests (start of season, and season complete) and by ADR 0027's measurements in between.
- How ESPN lists a season's future matchups in-season → not relied on. The count of
  scheduled matchups comes from the settings, which hold it before the season starts (C9).

## Requirements

### R1. The history weight is the season's matchups not yet played

- R1.1 THE SYSTEM SHALL, for a category that uses history (at least
  `fantasy_scale_prior_matchups` earlier matchups, as now), blend the scale as ADR 0027
  does: √((S + w·p²) / (n + w)). The weight `w` SHALL be the league-season's scheduled
  regular-season matchups less its decided ones measured in the category: w = max(0,
  M − n), not the fixed 100.
- R1.2 THE SYSTEM SHALL take M, a league-season's scheduled regular-season matchups, from
  its settings: the number of regular-season matchup periods times the matchups in each,
  floor(team count / 2).
- R1.3 WHEN a league-season has decided no matchup in a category THE SYSTEM SHALL scale
  it by the earlier seasons alone (p), as now.
- R1.4 WHEN every scheduled regular-season matchup is decided and measured (n ≥ M) THE
  SYSTEM SHALL scale the category by the season's own matchups alone.
- R1.5 THE SYSTEM SHALL weight a rate's side denominator by the same `w`, as ADR 0027
  does: (D + 2w·q) / (2n + 2w).
- R1.6 THE SYSTEM SHALL scale a category that does not use history (scale source
  `current_season`) as today.
- R1.7 THE SYSTEM SHALL report, per category and league-season, M and the `w` used.
- R1.8 IF a league-season with rosters has no readable, positive M (the matchup period
  count or the team count missing, or a product of 0) THEN THE SYSTEM SHALL scale its
  categories as ADR 0027 does, with a weight of `fantasy_scale_prior_matchups`, and SHALL
  warn, naming the league-season (owner, 2026-10-18). *Amended 2026-10-18 (design.md,
  Amendments): a missing team count still fails the build, at the existing `not_null` test
  of `stg_espn__league_settings.team_count`; the fallback and warning cover a missing
  matchup period count and an M of 0 or below.*
- R1.9 IF a league-season's decided regular-season matchups in a category exceed its M
  (the schedule was extended after the newest settings capture) THEN THE SYSTEM SHALL warn,
  naming the league-season and both counts, and SHALL scale the category with a weight of
  0, the season's own.

### R2. The values and the check that holds them

- R2.1 THE SYSTEM SHALL compute every value fact, the lineup options and the optimal
  lineups from the scales of R1, with no other change to how they are computed.
- R2.2 THE SYSTEM SHALL keep `values_track_rescored_category_wins` unchanged, and SHALL
  pass it on the eight seasons.
- R2.3 THE SYSTEM SHALL keep `int_fantasy__category_scales` and the models it feeds
  that are in the BigQuery slice in the slice, written once for both warehouses.

## Expected values

Counted on a prototype on 2026-10-18 (design.md, C6 and C10): the real warehouse built
from `main` at 718d494 (`data/warehouse_160_base.duckdb`), with everything downstream of
the scales rebuilt at a history weight of 0.001. That approximates R1 for a completed
season, where every season's n equals its M (C5) and the weight is exactly 0.

So the slopes and the 2018 rows are checked as given, while the row counts are estimates.
A count that differs at build time is explained, not a failure, provided only the
relations named here move. Recounted at build time from a build of the branch.

| Check | Expected | How to verify |
|---|---|---|
| M (R1.2) | 126 in 2018, 2019 and 2021 to 2023 and 2026; 138 in 2024; 132 in 2025 (12 teams; 21, 23 and 22 periods) | the new column |
| `w` at season end (R1.4) | 0 for every category that uses history, in every season | the new column |
| Scales | every category using history moves to the season's own scale (119 of 139 rows, 2019 to 2026); 2018's 18 and the 2 `current_season` rows of 2019 and 2022 unchanged | compare with the base |
| 2023 SP slope | 0.3333 → 0.3474 | `rec_fantasy__category_wins_by_group` |
| Every judged group | inside 0.34 to 0.47: SP 0.3474 to 0.4271, hitters 0.3623 to 0.4207 from 2019 (2018 unchanged at 0.3874 and 0.3985) | the view; C6 |
| `values_track_rescored_category_wins` | 1 → 0 failing rows | the test |
| `rec_fantasy__category_wins_added` | unchanged: it uses no scale | compare |
| `fct_player_season_value` | 3,676 of 4,240 rows change, all 2019 to 2026; 2018 unchanged | compare |
| `fct_player_category_value` | 29,889 of 73,553 rows change, 2019 to 2026 | compare |
| Lineups | `int_fantasy__optimal_lineups` 1,888 of 162,990 rows change, and `fct_lineup_decision_categories` 871 of 40,366, from 2019 on. The values every lineup choice is ranked by move, but a choice changes only where it was close | compare |
| `fct_transaction_impact` | 686 of 737 rows change (2026, the season with a log) | compare |
| New columns | `stg_espn__league_settings.matchup_period_count`; `int_fantasy__category_scales.scheduled_matchups` and `history_weight` | the schema |
| Decided matchups beyond M (R1.9) | none in any season | the warning test |
| Every other relation | identical | `scripts/compare_warehouses.py`, or a per-relation count where memory needs it (C10) |
