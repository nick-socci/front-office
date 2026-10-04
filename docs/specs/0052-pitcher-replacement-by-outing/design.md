# Pitcher replacement level by kind of outing — design

Issue: #52 · Requirements: [requirements.md](requirements.md) · Tasks: [tasks.md](tasks.md)

## Overview

Today a pitcher is put in a group (`SP` or `RP`) and every day he pitches is compared with
that group's free-agent pool. This design drops the pitcher groups. Each pitched day is a
`start` or a `relief` appearance, each kind has its own pool of free agents ranked by how
often they made that kind of appearance, and a pair's pitching value is the sum of its
starts against a replacement start and its relief appearances against a replacement relief
appearance. Hitters, the per-played-day unit, the standardisation and every grain are
untouched. Four models change; none is added.

| Model | Change |
|---|---|
| `int_fantasy__replacement_levels` | keyed by `day_kind` (`batting`, `start`, `relief`); pitching pools by kind, ranked by appearances |
| `fct_player_category_value` | pitching categories summed over kinds; `replacement_group` removed |
| `fct_transaction_impact` | the same, for a window |
| `dim_players` | `pitcher_slot_replacement_group` removed |
| `stg_espn__roster_entry_slots` | documentation only: eligibility is as of fetch |

### dbt concepts this touches

Nothing new is introduced. Two things from #11 are leaned on harder:

- **A macro as a shared rule.** A dbt macro is a Jinja function that returns SQL text.
  The rule "is this pitched day a start or a relief appearance" is needed by three models
  that must agree, so it is one macro, as `fo_replacement_group` already is.
- **Unit tests pin the rule; data tests check the season.** A `unit_tests:` block feeds a
  model hand-written rows and asserts the exact output. The mixed pair (some starts, some
  relief days) is proved there, because nothing in a data test can say what the right
  answer for a real pair is.

## Alternatives considered

### What a pitcher's day is compared with (the main fork)

All three measured on the 2026 season with the same pools (by kind of outing, ranked by
appearances, ties by outs then id), except option 1, which needs player groups: its free
agents are grouped by 5 starts and 8 relief appearances, an unverified imitation of ESPN.

| | Option 3 — by kind of outing (chosen) | Option 2 — by slot | Option 1 — three groups by eligibility |
|---|---|---|---|
| Compares | a start with a replacement start, a relief appearance with a replacement relief appearance | an `SP`-slot day with a replacement start, an `RP`-slot day with a relief appearance, a `P`-slot day by outing | each pitcher's days with his eligibility group's pool |
| Like with like, per played day | yes | no, on 130 of 5,254 days | no: the swingman pool is 700 days, 89 of them starts |
| Data it needs | MLB game logs | the day's slot (historical) | the day's eligibility (**not historical**), and a made-up grouping for free agents |
| Reliever-only pairs, median | +0.57 | +0.54 | +0.53 |
| `RP`-default swingmen, median | +3.92 | +1.78 | +3.98 |
| IP standard deviation (outs) | 25.4 | 40.9 | 53.4 |
| Credit for dual eligibility | none | yes, about 12 outs per start made from an `RP` slot | indirectly |

**Option 3 — by kind of outing.** The unit of value is the played day
([ADR 0002](../../adr/0002-value-is-measured-per-played-day.md)), and a played day of
six innings and a played day of one are not the same unit. Comparing within a kind is the
only version in which "per played day" compares like with like. It needs nothing from
ESPN beyond who was started.

**Option 2 — by slot.** It answers a real question: what did he add over what would
otherwise fill that slot. But the honest unit for that question is the slot-day: a starter
in an `RP` slot gives 15 outs once and then leaves the slot empty for four days, where a
reliever would have pitched twice. Per played day counts the 15 and not the four empty
days, so it overstates exactly the advantage it is meant to credit. ADR 0002 already
gave slot-days to #12. In practice it differs from option 3 on 2.5% of days.

**Option 1 — by eligibility.** How the league's managers see pitchers, but not buildable
honestly. Eligibility in the 2026 capture is as of the fetch date (see
[Evidence](#evidence)), and free agents have no eligibility at all, so the three pools
would be grouped by imitating ESPN's thresholds, which nobody here has verified. It also
breaks spec 0011's "three groups only" no-go and still mixes starts with relief days
inside the swingman group.

### How a pitching pool is ranked

Within option 3, the ranking decides more than the grouping does.

| Relief pool, top 12 by | Outs / app. | SV+HD / app. | ERA | Reliever-only median |
|---|---|---|---|---|
| Appearances (chosen) | 2.80 | 0.256 | 3.49 | +0.57 |
| Outs (ADR 0001's rule) | 4.20 | 0.201 | 3.35 | −0.56 |
| Saves + holds (#52, pool C) | 2.90 | 0.36 | 2.83 | not measured |
| No ranking: every free-agent relief appearance | 3.58 | 0.201 | 4.24 | +0.39 |

Rostered relief appearances, for scale: 3.01 outs, 0.452 SV+HD, ERA 3.37. Outs selects
long men and so does not fix the problem. Saves plus holds selects on a scored category
and is a floor better than the players above it. No ranking gives a weaker ERA floor but
a longer outing than a rostered reliever's, because lightly used free agents are bulk
arms (5.20 outs an appearance for those with under 10), so it charges relievers for
innings again. Appearances selects the relievers
managers use the way rostered relievers are used
([ADR 0009](../../adr/0009-a-pitching-pool-is-ranked-by-appearances.md)).

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0008](../../adr/0008-a-pitchers-day-is-measured-against-the-same-kind-of-outing.md) | A pitcher's day is measured against a replacement day of the same kind (start or relief) | accepted |
| [0009](../../adr/0009-a-pitching-pool-is-ranked-by-appearances.md) | A pitching pool is the top N free agents by appearances of that kind | accepted |

Both partly supersede [ADR 0001](../../adr/0001-replacement-level-is-the-free-agent-pool.md)
(its `SP` and `RP` groups, and "outs for pitchers"). ADRs 0002, 0003, 0005, 0006 and 0007
are unchanged.

## Detailed design

### `fo_pitching_day_kind` (new macro)

`fo_pitching_day_kind(games_pitched, games_started)` returns `'start'` when
`games_started > 0`, `'relief'` when `games_pitched > 0` and he started none, and null
when he did not pitch. The arguments are a day's columns. A date with both a start and a
relief appearance is a start; 2026 has no such date. Used by the replacement model and
both value facts.

### `int_fantasy__replacement_levels` (changed)

Grain: one row per (`day_kind`, `component`). `day_kind` replaces `replacement_group` as
the key and takes `batting`, `start`, `relief`. Other columns keep their names and
meaning: `pool_players`, `pool_played_days`, `pool_total`, `level_per_played_day`.

1. *Free-agent days*: unchanged.
2. *Batting pool*: unchanged. Free agents whose `fo_replacement_group` over their
   free-agent days is `hitter`, top N by plate appearances, ties by `mlbam_player_id`;
   played days are those with `games_batted > 0`; batting components only. Only the key
   value is renamed, `hitter` to `batting`.
3. *Pitching pools*: for each kind, every free agent with at least one free-agent day of
   that kind, ranked by the count of those days descending, then by outs recorded on
   them descending, then by `mlbam_player_id`; the top N, N = `count(*)` of
   `int_fantasy__teams`. No player group is consulted. A player may be in both pitching
   pools (none is in 2026).
4. *Level*: pitching components summed over the pool's free-agent days **of that kind
   only**, divided by the count of those days. A relief-pool member's spot start is in
   neither his pool's total nor its days.
5. *Every kind gets its rows*: the spine is the three kinds crossed with their
   components (16 batting, 16 pitching each), left-joined to the pools, so an empty pool
   gives null levels, as today.

The header restates the definition, the bias (never-owned players; the most-used
relievers are good ones, so relief ERA is close to rostered relievers') and the measured
levels at N/2, N and 2N.

### `fct_player_category_value` (changed)

Grain and row set unchanged. The change is inside the pitching side.

- **The row set comes from a spine, not from the days.** The output starts from every
  pair (the distinct pairs of `int_fantasy__started_player_days`) crossed with the scored
  categories, and the per-kind values are left-joined to it. 266 of the 580 pairs have no
  pitched day and so no `start` or `relief` group; without the spine they would lose their
  eight pitching rows. A category with no played day on its side has numerator 0,
  denominator 0 for a rate and null for a count, `played_days` 0 and value 0, as today.
- Component totals are grouped per pair and per `day_kind`: `batting` for hitter-slot
  days, and `fo_pitching_day_kind` for pitcher-slot days. A started day that is not a
  played day on its slot's side belongs to no kind and adds nothing: its credited
  components are all zero, since they come from the same MLB row as `games_batted` and
  `games_pitched`.
- For each (pair, `day_kind`, category) the existing macros give numerator, denominator
  and value over replacement against that kind's level:
  count `N − rN × played_days`, rate `N − (rN / rD) × D`, signed so positive is better.
- The row for (pair, category) sums over kinds: `numerator`, `denominator` and
  `played_days` are plain sums. `value_over_replacement` is the sum of the per-kind
  values, **null if any kind with played days has a null value** (a plain `sum` would
  skip the null and report a partial value as complete).
- `contribution`, `standardised_value` and the standard deviation are computed from those
  sums exactly as now: population standard deviation over pairs with `played_days > 0` on
  the category's side.
- `replacement_group` is removed: a pitching row can rest on two levels.
- The join to `dim_players` goes; nothing about the player is needed.

### `fct_player_season_value` (unchanged SQL)

Reads the category fact. `total_value` moves for pitchers.

### `fct_transaction_impact` (changed)

Windows, counts, component columns and row set unchanged. Only `total_value` moves.

- Add: the window's started pitcher-slot days are split by `fo_pitching_day_kind`, as in
  the season fact.
- Drop: his MLB days in the window, on the side his `dim_players.replacement_group`
  credits (unchanged), with pitching days split by kind. `SP` versus `RP` no longer
  matters; only hitter versus pitcher does.
- The per-kind arithmetic and the null rule are the season fact's. The standard deviation
  is still read from the season fact.

### `dim_players` (changed)

`pitcher_slot_replacement_group` is removed, with its unit test: it existed to choose
between two pitcher levels and nothing reads it now. `replacement_group` stays as it is.

### `stg_espn__roster_entry_slots` (documentation only)

The header and YAML description say eligibility is a daily snapshot and that consumers
must use the day's own row. For any period fetched after the fact it is the eligibility
at fetch time. Both are rewritten to say so, with the evidence below, and to say that
only a capture made on the day carries that day's eligibility. No SQL changes.

## Test strategy

| Requirement | Test | Catches |
|---|---|---|
| R1.2 | unit test on the replacement model: a free agent with one start day and two relief days contributes the start to `start` and the relief days to `relief` | a day classified by the player rather than the outing |
| R1.2 | unit test: a day with `games_pitched = 2`, `games_started = 1` is a `start` | a doubleheader day with both kinds read as relief (none in 2026, so only a unit test can hold the rule) |
| R1.3 | unit test: three free agents, N = 2, two tied on relief days; the one with more outs is in, then the lower id | ranking by outs; an arbitrary tie at the cut |
| R1.3 | existing `int_fantasy__replacement_pool_is_at_most_n`, re-keyed to `day_kind` | a pool cut at the wrong size |
| R1.4 | unit test: a relief-pool member's start day is in neither `pool_total` nor `pool_played_days` | a swingman's starts leaking back into the relief level |
| R1.5 | existing hitter unit tests, key renamed; expected value AVG .2416 on the real season | the batting pool moving |
| R1.6 | existing empty-pool unit test, for kind `relief` | an empty pool reading as zero |
| R1.1, R4.1 | `accepted_values` on `day_kind`; unique on (`day_kind`, `component`) | a stray group value |
| R2.1 | unit test on the category fact: a pair with one start (18 outs) and one relief day (3 outs), levels 15 and 3, has IP value +3 | the pair being measured against one level |
| R2.2 | unit test: a pair with a relief day and a null relief level has a null pitching value even though its start is valued | a partial sum reported as complete |
| R2.3 | unit test above asserts `played_days = 2`; existing `fct_player_season_value_day_counts_hold`, with its `replacement_group` assertion removed and its played-day reconciliation kept | played days counted per kind and not summed |
| R2.1 | existing `…has_a_row_per_pair_and_category`; unit test: a hitter-only pair still has its pitching rows, valued 0 | pairs with no pitched day losing rows to the per-kind grouping |
| R2.4 | unit test: two pairs with identical days and different default positions get identical rows | a label still choosing a level |
| R2.5 | last task: batting rows compared with the pre-build snapshot | hitters moving |
| R1, R2 | existing `…the_replacement_pool_is_worth_zero`, per `day_kind` | formula drift between pool and players |
| R3.1, R3.2 | unit tests on `fct_transaction_impact`: an add with a start and a relief day; a dropped pitcher with both kinds after the drop | a window valued against one level |
| R3.3 | existing `…an_add_covering_a_pair_reproduces_the_season_fact` | the two facts drifting |
| R3.1, R3.2 | last task: the four sums of `total_value` in the expected values, measured independently of the model | plausible but wrong window arithmetic that the synthetic tests pass |
| R4.2, R4.3 | YAML column lists; `accepted_values` on `dim_players.replacement_group` kept | a removed column lingering |
| R5.1 | review of the header and description | the claim surviving |

Existing unit tests that feed `replacement_group: SP`/`RP` levels or
`pitcher_slot_replacement_group` are rewritten to the new keys. Their expected values
change only where a row's level changes, and each such change is stated in the test's
description. Tests are written before the models they test.

## Risks

- **Starters dominate the ranking.** Certain: 15 of the top 20 total values are starters
  (from 9) and hitters fall from 11 to 5. With like compared with like, innings spread
  less, so a standard deviation of innings is 25.4 outs, not 115.6, and a starter who
  goes deep earns more of them. This is ADR 0003's shared standard deviation working as
  written; it is surfaced for the owner's eye test, not adjusted.
- **A strong relief floor.** Replacement relief ERA (3.49) is close to rostered
  relievers' (3.37), so reliever-only pairs average +0.04 on ERA and +1.26 on SV+HD.
  Accepted in ADR 0009.
- **Most pitcher transactions move.** 210 of 223 pitcher adds and 189 of 210 pitcher
  drops change `total_value`; no hitter transaction does. The sums are expected values,
  and 76 windows (10 adds, 66 drops) hold both kinds of outing.
- **CI fixtures.** The fixture warehouse has 3 free-agent start days and 9 relief days,
  so both pools are non-empty and no fixture change is expected. Started pitching days in
  fixtures: 1 start, 3 relief.
- **Removing two mart columns breaks a reader.** Unlikely: both were added in #51 two
  days ago; task 1 greps.

## Open questions

- **What ESPN's eligibility thresholds are** (recalled as 5 starts and 8 relief
  appearances; not verified). Nothing chosen depends on it.
- **Whether a live capture carries that day's eligibility.** Believed so, and it is what
  #27 would give from 2027. No live capture exists to check.
- **The eye test.** The numbers below are measured; whether the top and bottom 20 look
  right to someone who watched the season is the owner's call, recorded on #52.

## Evidence

Read-only queries against `data/warehouse.duckdb` and `data/raw/`, run 2026-10-03. The
harness reproduces the built `fct_player_season_value.total_value` for all 580 pairs to
7e-15 under the current definition before any option is measured.

| Claim | Measured |
|---|---|
| The issue's numbers reproduce | `RP` pool 12 players, 441 days, 122 starts, 8.71 outs, 2.41 K, ERA 4.13; medians RP −0.35 (107), SP +0.94 (212), hitter +0.78 (261) |
| Eligibility is as of fetch | every roster period 1–180 was fetched at 2026-09-26 16:23 UTC; 0 of 493 players (227 hitters, 128 of them rostered 120+ periods) change eligible slots across periods |
| …proved by two captures | the pre-pipeline capture of 2026-09-21 and the pipeline's of 09-26 disagree on 494 of 59,930 player-periods, 4 players: three pitchers `P,SP` then `P,SP,RP`, one hitter gaining `2B`, on periods as early as 1 |
| The slot is historical | 0 of 38,665 started rows sit in a slot outside the player's eligible set |
| Started pitching days | 5,254: `SP` slot 1,931 starts + 112 relief; `RP` slot 1,381 relief + 18 starts; `P` slot 575 starts + 1,237 relief |
| By eligibility as fetched | RP only: 2,513 relief days at 2.88 outs, 2 starts. SP + RP: 348 starts at 15.56, 204 relief at 4.21. SP only: 2,174 starts at 16.54, 13 relief |
| Free-agent pitching days | 1,875 start days by 282 players; 12,523 relief days by 695 |
| Pools at N = 12 | start: 306 days, 4,584 outs, ERA 5.41, WHIP 1.48. Relief: 833 days, 2,334 outs, 213 SV+HD, ERA 3.49, WHIP 1.26. No player in both |
| The relief cut is a tie | ranks 10–13 all have 66 appearances (187, 214, 144, 196 outs); by id alone the 144-out pitcher is in and the level is 2.74 outs; by outs then id, 2.80 |
| Ranking by outs does not fix it | relief pool 661 days, 4.20 outs, ERA 3.35; reliever-only median −0.56, IP −1.05 sd |
| The unranked pool | relief: 695 pitchers, 12,523 days, 3.58 outs, 1.11 K, 0.201 SV+HD, ERA 4.24, WHIP 1.35; start: 282 pitchers, 1,875 days, 13.47 outs, ERA 4.84. Medians: RP +0.62, SP +1.16; reliever-only +0.39, IP −0.48 sd; 20+ save pairs median +6.25, 1 negative, worst 82nd from the bottom. Outs per free-agent relief appearance by appearances made: 1–9 5.20 (349 pitchers), 10–19 4.57, 20–39 3.37, 40+ 3.12 |
| Chosen definition | medians: RP +0.67, SP +1.52, hitter +0.78; reliever-only +0.57 (86), `RP`-default swingmen +3.92 (21), SP-only +2.29 (170), `SP`-default swingmen −0.02 (42) |
| Reliever-only, by category (sd) | IP +0.08, K +0.29, W +0.06, L −0.31, SV+HD +1.26, ERA +0.04, WHIP +0.07, K/9 +0.32 (were −1.47, −1.06, −0.86, +1.11, +1.43, +0.20, +0.12, +0.50) |
| Closers | 15 pairs with 20+ saves: median +2.76 → +6.87; 3 negative → 0; the 36-save pair ranked 8th worst → 240th from the bottom |
| Top and bottom 20 | top 20: SP 9 → 15, hitter 11 → 5, RP 0 → 0. Bottom 20: RP 8 → 2, SP 2 → 5, hitter 10 → 13 |
| Hitters | 260 of 261 hitter pairs unchanged; the one two-way player's 15 pitcher-slot days move him by about +2.8 |
| Transaction impact | the harness reproduces all 737 built `total_value`s exactly under the current definition. New sums: pitcher adds 220.94 → 426.05 (223), pitcher drops 208.18 → 440.35 (210); hitter adds 172.17 (151) and drops 134.42 (153) unchanged |
| Pairs with no pitched day | 266 of 580 |
| Rank agreement with today | correlation of new and current `total_value`: 0.974 overall, 0.996 SP, 0.948 RP |

## Review log

| Source | Finding | Resolution |
|---|---|---|
| design-review 2026-10-03 | F1 (P1): grouping pitching by kind gives the 266 pairs with no pitched day no group, so they would lose their pitching rows | Changed: the category fact is built from a pair × category spine; unit test for a hitter-only pair; the existing row-count test named |
| design-review | F2 (P1): `fct_player_season_value_day_counts_hold` reads the `replacement_group` column being removed | Changed: task 5 and the test strategy rewrite it, keeping the played-day reconciliation |
| design-review | F3 (P2): no numerical acceptance values for the transaction impacts that change | Changed: measured independently (harness matches all 737 built totals first); four sums and the counts of moved and mixed windows are expected values |
| design-review | F4 (P2): the rule that a date with both kinds is a start is untested | Changed: unit test with `games_pitched = 2`, `games_started = 1` |

## Amendments

### 2026-10-03 — batting rows are identical in value, and equal to 1e-12 when standardised

Found in task 5. Against the pre-build snapshot all 5,220 batting rows of
`fct_player_category_value` have bit-identical `numerator`, `denominator`, `played_days`,
`contribution` and `value_over_replacement`. `standardised_value` differs on 2,038 of them
by about 1e-15 (the largest seen is 1.8e-15, and it varies from build to build): DuckDB's `stddev_pop` depends on the order rows reach it, and the
spine changes that order, so the standard deviation moves in its last bit. The expected
value "identical in `standardised_value`" is read as equal within 1e-12; R2.5's intent,
that nothing about hitters changes, holds. No decision changes.

### 2026-10-03 — what the spine fills in, and which components a kind meets

Task 5. Two things the design implied and the model now states. A (pair, category) with
no played day on its side takes denominator 0 when the category is a rate and null when
it is a count, "rate" meaning the category has a denominator part in
`int_fantasy__stat_components`. And a kind's totals meet only the components of its own
side (`batting` with batting components, `start` and `relief` with pitching ones).
