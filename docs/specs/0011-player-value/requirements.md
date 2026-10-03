# Player value and transaction impact — requirements

Issue: #11 · Tier: M · Status: draft

## Problem

The marts can say which team won each category of each matchup (#10), but not which
players produced that, or whether an add or a drop helped. The original plan
([milestone 10](../../design/02-intermediate-and-marts.md)) set out three models. Grounding
it against the 2026 season (queries recorded in [design.md](design.md#evidence)) showed
that plan cannot be built as written:

- Its replacement level, "the median production of a rostered-but-benched player", is
  **zero in every position group**, because benched players mostly are not playing
  (benched starting pitchers appear on 4.0% of bench days). Value over that replacement
  would simply be raw production.
- `stg_espn__transactions` does not carry the acting team for 111 of 363 drops, and
  names the column that does carry it for the other 252 `to_team_id`.
- 245 started player-days fall outside every matchup (two teams, 2026-08-31 to
  09-06), so player contributions cannot equal #10's team totals without saying which
  days count.

## Goals

- A team's credited season production is broken down by the players who produced it,
  and adds back up to every matchup side's totals from #10. (The day-by-day trace
  already exists in `int_fantasy__started_player_days`; this adds the season view.)
- Each (player, fantasy team) has a value over a stated, defensible replacement level,
  per category and as one summary number.
- Each add and each drop has a measured outcome.
- A reader can see how every player was matched between ESPN and MLB.

## No-gos

- **No lineup optimisation or "should have started" analysis.** That is milestone 11 (#12).
- **No change to how production is credited** (slot role, doubleheaders, `input_status`).
  Those are #10's and #25's, and are consumed as they stand.
- **No multi-league or multi-season identity work.** `stg_espn__transactions` has no league
  or season column; fixing that is R2 (#28). This spec assumes the one league-season
  staging holds and says so where it matters.
- **No trades.** 2026 has none (0 of 737 messages). The interface must not mis-handle one
  silently (R2.4), but trade impact is not designed here.
- **No per-hitter-position replacement levels** (catcher vs outfield). Three groups only —
  see [ADR 0001](../../adr/0001-replacement-level-is-the-free-agent-pool.md).
- **No new ingestion.** Everything is built from data already landed.
- **No tolerance widening** to make a reconciliation pass.

## Rabbit holes

- *Tuning the replacement pool until values "look right"* → the pool size is the number of
  fantasy teams, the sensitivity at half and double that is reported, and that is all.
- *Per-category weights for the summary number* → equal weights, weakness stated
  ([ADR 0003](../../adr/0003-total-value-is-a-sum-of-standardised-category-values.md)).
- *`dbt_utils.date_spine`*, named in the issue as a concept to learn → not needed: roster
  days and MLB game days already hold every date these windows touch. Adding a spine to
  have used one would be a dependency with no job.
- *Naming the five transaction-only players* (in the log, never on a roster snapshot) →
  they get a `dim_players` row with whatever the id map resolves, and no further chase.

## Requirements

### R1. Player dimension

One row per player the league touched, showing how he was matched to MLB.

- R1.1 THE SYSTEM SHALL provide `dim_players` with exactly one row per platform player
  id that appears on any roster day or in any transaction.
- R1.2 THE SYSTEM SHALL record on each row the MLBAM id (nullable), the resolution method
  (`crosswalk_id`, `unambiguous_name`, `unresolved`), the latest default position, and
  the replacement group (`hitter`, `SP`, `RP`).
- R1.4 WHEN a player has no default position (he appears only in transactions) THE
  SYSTEM SHALL derive his replacement group from his MLB appearances by the same rule
  the free-agent pool uses, and leave it null only if he is unresolved.
- R1.3 IF a player cannot be resolved to an MLBAM id THEN THE SYSTEM SHALL keep his row
  with resolution `unresolved` rather than drop it.

### R2. Transactions interface

A platform-neutral record of who added or dropped whom, and when.

- R2.1 THE SYSTEM SHALL provide `int_fantasy__transactions` with one row per transaction
  message, carrying the acting fantasy team, the player, the movement (`add` or `drop`),
  the method, and the transaction date.
- R2.2 THE SYSTEM SHALL take the acting team from the field the message type defines
  (per [ADR 0004](../../adr/0004-a-transactions-acting-team-depends-on-its-message-type.md)),
  with the rule held in the `espn_activity_types` seed rather than in SQL.
- R2.3 THE SYSTEM SHALL expose the ESPN message fields in staging under names that do not
  claim a meaning they lack (`to`, `from` and `for` are not all team ids).
- R2.4 IF a message type has no movement and team rule in the seed (a trade, or a type
  ESPN adds) THEN THE SYSTEM SHALL fail the build rather than guess.
- R2.5 THE SYSTEM SHALL fail the build if any transaction's acting team is null or is not
  a team of the league.

### R3. Replacement level

- R3.1 THE SYSTEM SHALL define replacement level per group (`hitter`, `SP`, `RP`) as the
  pooled production of the top *N* free agents in that group by playing time, where a
  free agent is an MLB player on no fantasy roster that date and *N* is the number of
  fantasy teams in the league.
- R3.2 THE SYSTEM SHALL express replacement level as components per played day and as
  rates from pooled components, never as an average of per-player rates.
- R3.3 THE SYSTEM SHALL state the definition, and the replacement rates at *N*/2 and 2*N*,
  in the model header.
- R3.4 IF a group's pool is empty THEN THE SYSTEM SHALL still produce that group's rows,
  with null levels, so that values over replacement for the group are null rather than
  computed against zero or silently dropped.
- R3.5 THE SYSTEM SHALL count a played day on the credited side only: a day batted for
  the hitter group, a day pitched for `SP` and `RP`.

### R4. Player value

- R4.1 THE SYSTEM SHALL provide `fct_player_category_value` with one row per (player,
  fantasy team, scored category) for every pair with at least one started day, holding
  the numerator and denominator components, the contribution while started, the value
  over replacement, and the standardised value.
- R4.2 THE SYSTEM SHALL compute contributions from credited components of
  `int_fantasy__started_player_days` through `int_fantasy__stat_components`, with the
  category list from `int_fantasy__categories`; no category, stat id or count of
  categories is hardcoded.
- R4.3 THE SYSTEM SHALL sign every value over replacement so that positive is better,
  including for categories where lower is better.
- R4.7 WHEN a started day has no appearance on the side its slot credits THE SYSTEM SHALL
  NOT count it as a played day, whatever the player did on the other side.
- R4.8 IF a category's values have zero standard deviation THEN THE SYSTEM SHALL give
  every standardised value in it as 0.
- R4.4 THE SYSTEM SHALL provide `fct_player_season_value` with one row per (player,
  fantasy team): days started, days played while started, days started outside any
  matchup, days resting on unverified inputs, and the total value.
- R4.5 WHEN a started day's `input_status` is neither `played` nor `verified_off` THE
  SYSTEM SHALL count it in `unverified_started_days` and not present its zeroes as
  verified.
- R4.6 THE SYSTEM SHALL include started days outside any matchup in a player's value and
  report their count separately
  ([ADR 0006](../../adr/0006-player-value-counts-every-started-day.md)).

### R5. Reconciliation to #10

- R5.1 THE SYSTEM SHALL fail the build if, for any matchup side and any credited
  component, the sum of player contributions over that matchup's days differs from that
  side's row of `int_fantasy__matchup_side_totals`, including sides that started nobody.
- R5.2 THE SYSTEM SHALL fail the build if started days inside matchups plus started days
  outside matchups differ from the rows of `int_fantasy__started_player_days`.

### R6. Transaction impact

- R6.1 THE SYSTEM SHALL provide `fct_transaction_impact` with one row per transaction.
- R6.2 WHEN the movement is an add THE SYSTEM SHALL report what the player produced for
  the acting team while started, from the add until that team next dropped him or the
  season ended.
- R6.3 WHEN the movement is a drop THE SYSTEM SHALL report everything the player produced
  in MLB from the day after the drop to the end of the season, and whether and when a
  fantasy team next added him
  ([ADR 0005](../../adr/0005-a-drops-impact-is-the-rest-of-the-season.md)).
- R6.4 WHEN a transaction predates the first scoring date THE SYSTEM SHALL start its
  window on the first scoring date.
- R6.5 THE SYSTEM SHALL report each transaction's total value on the same replacement
  level and scale as R4.

## Expected values

2026 season, warehouse built 2026-10-01. Fixtures in CI prove structure; these prove the
numbers, and are checked against the real season in the last task.

| Check | Expected | How to verify |
|---|---|---|
| `dim_players` rows | 498 = 493 rostered + 5 transaction-only | row count; `unique` on player id |
| Players resolved | 0 `unresolved` among the 493 rostered | group by resolution |
| `int_fantasy__transactions` rows | 737 = 374 adds (354 free agent + 20 waiver) + 363 drops | group by movement, method |
| Acting team | not null and in 1–12 on all 737 | R2.5 test |
| Drops name the right team | every drop whose player was on a roster the day before names that roster's team (measured: 89 of 89 for type 239; 241 of 252 for types 179/181, the rest pre-season or not rostered the day before) | singular test |
| `fct_player_season_value` rows | 580 (player, team) pairs, 481 players | row count |
| `fct_player_category_value` rows | 9,860 = 580 × 17 | row count |
| Started days | 38,665 = 38,420 inside matchups + 245 outside | R5.2 test |
| Matchup sides reconcile | exact, all 286 sides and every component; league-wide 15,080 hits and 49,305 outs inside matchups | R5.1 test |
| Replacement, hitters | pooled AVG .2416 at N=12 (.2410 at 6, .2420 at 24); first recorded as .237, corrected 2026-10-03 (design.md, Amendments) | query; model header |
| Replacement, SP | ERA 5.15, WHIP 1.45 at N=12 (ERA 5.07 / 5.00) | query; model header |
| Replacement, RP | ERA 4.13, WHIP 1.29 at N=12 (ERA 4.45 / 3.90) | query; model header |
| The pool is worth zero | pooled value over replacement of each group's own pool = 0 per category | singular test |
| `fct_transaction_impact` rows | 737 | row count; `unique` on transaction id |
| Pre-season transactions | 49 have their window start on 2026-03-25 | query |
| Two known transactions | match the ESPN activity log | by hand; recorded on #11 |
