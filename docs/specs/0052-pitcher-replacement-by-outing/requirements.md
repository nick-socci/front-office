# Pitcher replacement level by kind of outing — requirements

Issue: #52 · Tier: M · Status: approved 2026-10-03

## Problem

`int_fantasy__replacement_levels` measures every reliever against one `RP` pool: the top
12 unrostered pitchers who started fewer than half their games, ranked by outs. Ranking by
outs picks swingmen. The pool made 122 starts and averages 8.71 outs an appearance, against
3.01 for a rostered pitcher's relief appearance, so each relief appearance is charged about
5.7 outs and 1.3 strikeouts it was never going to produce. On 2026 the 86 reliever-only
(player, team) pairs have a median total value of −0.52, a 36-save closer is the 8th worst
of 580 pairs, and the `RP`-default swingmen who out-pitch that bulk pool sit at +2.53. The
measure has relievers backwards (#52; evidence in [design.md](design.md#evidence)).

Two facts found while grounding shape the answer:

- **The fix is mostly the ranking, not the grouping.** Splitting the pool by kind of outing
  but still ranking relievers by outs leaves reliever-only pairs at −0.56. Ranking them by
  appearances moves them to +0.57.
- **Roster eligibility is not historical.** Each scoring period's `eligibleSlots` is the
  player's eligibility when the payload was fetched, not on that day. The backfill is the
  only capture of periods 1–180, so no per-day eligibility exists for 2026.

## Goals

- A pitcher's day is compared with a replacement's day of the same kind: a start against
  a replacement start, a relief appearance against a replacement relief appearance.
- Relievers who did a reliever's job are no longer valued below a free agent for it.
- Nothing about hitters changes.
- The repo stops claiming that roster eligibility is a daily snapshot.

## No-gos

- **No change to hitters.** The hitter pool, its ranking and every batting category value
  and standard deviation stay as they are.
- **No change to the unit or the scalar.** Per played day
  ([ADR 0002](../../adr/0002-value-is-measured-per-played-day.md)) and the equal-weight sum
  of standardised values
  ([ADR 0003](../../adr/0003-total-value-is-a-sum-of-standardised-category-values.md))
  stand. The pitching standard deviations move as a consequence; how they are computed
  does not.
- **No credit for a slot.** What a starter is worth because he can sit in an `RP` slot is
  lineup construction, which is #12.
- **No use of eligibility in any value.** It is not historical (R5).
- **No new ingestion**, and no attempt to recover historical eligibility.
- **No change to how production is credited, to windows, or to grains.** Row counts of
  every model are unchanged.
- **No tolerance widening** and no test weakened to make a build pass. One comparison is
  stated to floating-point precision, not as a tolerance on a reconciliation: batting
  standardised values against the pre-build snapshot (R2.5, owner-approved 2026-10-03).

## Rabbit holes

- *Tuning the pool until relievers "look right"* → N stays the number of fantasy teams;
  the ranking is fixed by [ADR 0009](../../adr/0009-a-pitching-pool-is-ranked-by-appearances.md);
  the sensitivity at N/2 and 2N is reported and that is all.
- *Starters now crowd the top of the ranking* (15 of the top 20, from 9) → reported as a
  consequence of ADR 0003's shared standard deviation, for the owner's eye test. Not
  re-weighted here.
- *Imitating ESPN's eligibility thresholds from MLB usage* → not needed: no option that
  needs them is chosen.
- *Openers and bulk relievers* → an opener's day is a start and a bulk reliever's a relief
  appearance, by `games_started`. No third kind.

## Requirements

### R1. Replacement level by kind of played day

- R1.1 THE SYSTEM SHALL define a replacement level for each kind of played day: `batting`,
  `start` and `relief`.
- R1.2 THE SYSTEM SHALL classify a pitched day as `start` when the player started any game
  that date and as `relief` otherwise, by one shared rule used for free agents, started
  days and dropped players' MLB days.
- R1.3 THE SYSTEM SHALL form the `start` and `relief` pools from the top *N* free agents
  by number of free-agent days of that kind, *N* being the number of fantasy teams, with
  ties broken by outs recorded on those days and then by `mlbam_player_id`.
- R1.4 THE SYSTEM SHALL compute a pitching pool's level from its members' free-agent days
  of that kind only, as pooled components per played day.
- R1.5 THE SYSTEM SHALL leave the `batting` pool and level exactly as the `hitter` group's
  are today.
- R1.6 IF a kind's pool is empty THEN THE SYSTEM SHALL still produce that kind's rows with
  null levels.
- R1.7 THE SYSTEM SHALL state the definition, its bias and the levels at *N*/2, *N* and
  2*N* in the model header.

### R2. Player value

- R2.1 THE SYSTEM SHALL value a pair's pitching category as the sum, over `start` and
  `relief`, of the value of its days of that kind against that kind's level, using the
  existing arithmetic for counts and rates.
- R2.2 WHEN a pair has played days of a kind whose level is null THE SYSTEM SHALL give
  that category's value as null, not a partial sum.
- R2.3 THE SYSTEM SHALL report `played_days` for a pitching category as start days plus
  relief days.
- R2.4 THE SYSTEM SHALL NOT use a player's default position, eligibility or roster slot
  (`SP`, `RP`, `P`) to choose a pitching level.
- R2.5 THE SYSTEM SHALL keep every batting category row of `fct_player_category_value`
  identical in value over replacement, and equal in standardised value to floating-point
  precision (1e-12). *(Reworded 2026-10-03 with the owner's approval; see design.md,
  Amendments. It first read "unchanged in value and standardised value".)*

### R3. Transaction impact

- R3.1 WHEN the movement is an add THE SYSTEM SHALL value the window's started pitching
  days by kind, as R2.1.
- R3.2 WHEN the movement is a drop of a pitcher THE SYSTEM SHALL value his MLB pitching
  days in the window by kind.
- R3.3 THE SYSTEM SHALL keep an add whose window covers a pair's whole season equal to
  that pair's season total.

### R4. Columns that lose their meaning

- R4.1 THE SYSTEM SHALL key `int_fantasy__replacement_levels` by `day_kind` (`batting`,
  `start`, `relief`) in place of `replacement_group`.
- R4.2 THE SYSTEM SHALL remove `dim_players.pitcher_slot_replacement_group` and
  `fct_player_category_value.replacement_group`, which no longer select a level.
- R4.3 THE SYSTEM SHALL keep `dim_players.replacement_group` (`hitter`, `SP`, `RP`) as a
  description of the player, read only to tell a hitter from a pitcher.

### R5. Eligibility is documented as it is

- R5.1 THE SYSTEM SHALL describe `stg_espn__roster_entry_slots` as eligibility at fetch
  time, with the evidence, in the model header and its YAML description.

## Expected values

2026 season, `data/warehouse.duckdb` as of 2026-10-03, measured read-only with the queries
in [design.md](design.md#evidence). Fixtures prove structure; these prove the numbers and
are checked against the real season in the last task.

| Check | Expected | How to verify |
|---|---|---|
| Row counts | `dim_players` 498, `fct_player_season_value` 580, `fct_player_category_value` 9,860, `fct_transaction_impact` 737: all unchanged | row counts |
| `int_fantasy__replacement_levels` rows | 48 = 16 components × 3 kinds, unchanged | row count; unique on (`day_kind`, component) |
| Batting pool | 12 players, 1,690 played days, AVG .2416: unchanged | query; model header |
| Start pool | 12 players, 306 days, all starts; 4,584 outs (14.98 a day), 4.17 K, ERA 5.41, WHIP 1.48 | query; model header |
| Relief pool | 12 players, 833 days, no starts; 2,334 outs (2.80 a day), 0.89 K, 0.256 SV+HD, ERA 3.49, WHIP 1.26 | query; model header |
| Sensitivity, relief | outs 2.68 / 2.80 / 2.83 and ERA 3.18 / 3.49 / 3.58 at N = 6 / 12 / 24 | query; model header |
| Sensitivity, start | outs 14.84 / 14.98 / 15.01 and ERA 5.40 / 5.41 / 5.06 | query; model header |
| Pools do not overlap | 0 players in both pitching pools | query |
| Started pitching days | 5,254 = 2,524 start + 2,730 relief | query |
| Each pool is worth zero | value over replacement of each kind's own pool = 0 per category | singular test |
| Hitters | 260 of 261 hitter pairs' `total_value` unchanged to 1e-9; the one two-way player rises by about 2.8 | compare with the pre-build snapshot |
| Batting category rows | 5,220 rows (580 × 9) bit-identical in `value_over_replacement`; `standardised_value` within 1e-12 (measured: at most 1.8e-15) | compare with the pre-build snapshot |
| Pitching standard deviations | IP 25.4 outs (was 115.6), K 20.7 (36.5), SV+HD 4.55 (6.53), W 2.14 (2.84), L 2.01 (2.36), ERA 379.4 (337.8), WHIP 65.3 (59.6), K/9 442.1 (463.2) | query on the category fact |
| Transaction impact, pitchers | sum of `total_value`: adds 426.05 over 223 (was 220.94), drops 440.35 over 210 (was 208.18); 210 adds and 189 drops move | query, grouped by movement and hitter/pitcher |
| Transaction impact, hitters | sums unchanged: adds 172.17 over 151, drops 134.42 over 153; 0 rows move | same query; compare with the pre-build snapshot |
| Windows with both kinds | 10 adds and 66 drops | query |
| Pairs with no pitched day | 266 of 580, each still with 8 pitching rows valued 0 | query |
| Median `total_value` by `replacement_group` | RP +0.67 (was −0.35), SP +1.52 (+0.94), hitter +0.78 (unchanged) | query |
| Reliever-only pairs (86) | median +0.57 (was −0.52) | query, by eligibility as fetched |
| `RP`-default swingmen (21) | median +3.92 (was +2.53) | query |
| Closers | 15 pairs with 20 or more saves: median +6.87 (was +2.76), none negative (was 3), worst rank 240th from the bottom (was 8th) | query |
| Eye test | top and bottom 20, and the relievers, read by the owner | recorded on #52 |
