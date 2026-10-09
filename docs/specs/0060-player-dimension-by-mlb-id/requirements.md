# The player dimension is keyed by MLB id — requirements

Issue: #60 · Tier: L · Status: draft

## Problem

`dim_players` has one row per fantasy platform player id (ADR 0012). That makes it a
single reference within ESPN only, and it holds only the players a league touched. All
production is measured from MLB game logs, by MLB id, and most of the players in those
logs have no row and no name anywhere in the marts.

Measured on the real 2026 season, 2026-10-09:

- `dim_players`: 498 rows, 498 distinct MLB ids, none null. No MLB id is shared by two
  platform players. `dim_player_league_seasons`: the same 498, resolved 489 by the id
  map and 9 by the name fallback.
- `int_mlb__player_game_days`: 1,472 MLB players. 979 of them are in neither dimension.
  1,436 have at least one played day on which no team rostered them, which is the
  production the replacement pools are built from.
- 5 of the 498 have no MLB game in 2026 (rostered, never played), so no MLB name in
  what is landed.
- Each MLB id has one spelling across all 2026 boxscores. For the 493 players with a
  game, ESPN's name differs from MLB's for 37, in every case only by accents.
- The id map holds 1,209 of the 1,472, so it is not a source for the rest.

Nothing is wrong with a number today. The cost is structural: every mart joins players
through a key that is one platform's, and #12 is about to add another mart on it.

## Goals

- One row per MLB player, keyed by MLB id, for every player the warehouse holds
  production for, so any mart or query can name a player whichever league rostered him,
  or none.
- A stated path from a platform's player id to that row, true at the grain where the
  match is made.
- The 2026 numbers do not change.

## No-gos

- **No new ingestion.** No MLB people endpoint, no new landing folder. Attributes come
  from what is landed (ADR 0035). More attributes are a follow-up issue if wanted.
- **No change to how a player is resolved.** `int_fantasy__player_crosswalk` and its
  per-league-season name fallback stay as #28 left them.
- **No change to `dim_player_league_seasons`**: same rows, same columns, same values.
- **No re-keying of facts.** Each fact keeps its grain and its `platform_player_id`;
  the facts only gain a column (ADR 0034).
- **No change to any existing column of any model on 2026**, other than `dim_players`
  itself.
- **No player attributes beyond a name**: no position, handedness, team or birth date.
  A position is a fact about a game or a league-season, not about the player.
- **No second fantasy platform**, and no MLB season dimension.
- **The current warehouse is not replaced or deleted by an agent.**
- **No test weakened.** One singular test and one unit test are removed with the model
  they describe, and replaced (R4.4). The two value facts' one-column `relationships`
  test to `dim_players` is replaced by a stricter four-column test (R3.4). Both
  removals are listed for the owner's approval.

## Rabbit holes

- *A surrogate key* (a hash, or a sequence) so unresolved players can have a row → no:
  a player with no MLB id is a gap in resolution, already reported by a warning test,
  and stays visible in `dim_player_league_seasons`. The dimension's key is the MLB id
  itself.
- *Moving `default_position` or `replacement_group` onto the new dimension* → they are
  true of a league-season (ADR 0012) and stay there.
- *Fixing ESPN's accent-stripped names everywhere* → roster days and the league-season
  table keep the name the platform showed; only `dim_players` shows MLB's.
- *Comparing warehouses with `compare_warehouses.py`* → it stops at the first view of a
  copied warehouse (#101). The before/after comparison copies the affected tables to a
  scratch database and uses `except`, as #81 did.

## Requirements

### R1. `dim_players` is one row per MLB player

- R1.1 THE SYSTEM SHALL hold in `dim_players` exactly one row for each MLB id that
  appears in `int_mlb__player_game_days` or as a non-null `mlbam_player_id` in
  `dim_player_league_seasons`, over everything loaded, and no other row.
- R1.2 THE SYSTEM SHALL key `dim_players` by `mlbam_player_id`, unique and not null,
  with no platform, league or season column.
- R1.3 WHEN a player has at least one loaded MLB game line that names him THE SYSTEM
  SHALL set `player_name` to the name on the latest such line (latest official date,
  then highest game id) and `name_source` to `mlb`. A line with a null name is not
  considered.
- R1.4 WHEN no game line names him and at least one of his league-season rows has a
  name THE SYSTEM SHALL set `player_name` to the latest non-null name among those rows
  (highest season, then latest `last_rostered_date` with nulls last, then lowest
  `league_id`, then platform, then lowest platform player id) and `name_source` to
  `platform`. A later row with a null name (a transaction-only season) does not hide
  an earlier name.
- R1.5 IF nothing names him THEN THE SYSTEM SHALL keep his row with `player_name` and
  `name_source` null.
- R1.6 IF a platform player has no MLB id in any league-season THEN THE SYSTEM SHALL
  hold no `dim_players` row for him; he remains in `dim_player_league_seasons` as
  `unresolved`.

### R2. The path from a platform's player to an MLB player

- R2.1 THE SYSTEM SHALL leave `dim_player_league_seasons` unchanged: on the real 2026
  season its rows are identical before and after.
- R2.2 THE SYSTEM SHALL fail the build if a non-null `mlbam_player_id` in
  `dim_player_league_seasons` has no `dim_players` row.
- R2.3 WHEN one platform player has different non-null MLB ids in different
  league-seasons THE SYSTEM SHALL warn on every build, naming him; each league-season
  keeps its own id and both MLB players have a `dim_players` row.
- R2.4 THE SYSTEM SHALL hold no model with one row per platform player.

### R3. Facts carry the MLB id

- R3.1 THE SYSTEM SHALL add `mlbam_player_id` as the last column of
  `fct_player_category_value`, `fct_player_season_value` and `fct_transaction_impact`,
  equal to the `mlbam_player_id` of the row's own league-season in
  `dim_player_league_seasons`, and null where that is null.
- R3.2 THE SYSTEM SHALL keep each fact's grain, row count and every existing column
  unchanged, in name, order and value.
- R3.3 THE SYSTEM SHALL fail the build if a fact's non-null `mlbam_player_id` has no
  `dim_players` row.
- R3.4 THE SYSTEM SHALL fail the build if a fact row has no `dim_player_league_seasons`
  row for its own (`platform`, `league_id`, `season`, `platform_player_id`), or if its
  `mlbam_player_id` is distinct from that row's (nulls compared as equal).

### R4. Proof and safety

- R4.1 THE SYSTEM SHALL keep `dim_players` exempt, by name, from the tenant-isolation
  row comparison, and run its own tests in the combined build and in every single
  build.
- R4.2 THE SYSTEM SHALL hold R1.1 by a singular test that returns any MLB id present on
  one side of the equality and missing on the other.
- R4.3 THE SYSTEM SHALL hold R1.3 to R1.6 by a unit test with one case each.
- R4.4 THE SYSTEM SHALL remove `dim_players_equal_their_latest_league_season` and the
  unit test `dim_players_one_row_per_player_equal_to_his_latest_league_season`, which
  state the invariant of the model being replaced, in the same commit that adds the
  tests of R4.2 and R4.3.
- R4.5 THE SYSTEM SHALL pass `.agentic/gates`, with no warning that CI does not have
  today other than, possibly, the one of R2.3.

## Expected values

Real 2026 season (`data/warehouse.duckdb`), measured 2026-10-09 unless marked.

| Check | Expected | How to verify |
|---|---|---|
| `dim_players` rows / distinct `mlbam_player_id` | 1,477 / 1,477 | count |
| by `name_source` | 1,472 `mlb`, 5 `platform`, 0 null | group by |
| rows referenced by `dim_player_league_seasons` | 498; 979 are not | join |
| `dim_players.player_name` against the league-season name, for the 493 with a game | 37 differ, 0 differ once accents are stripped | join, `strip_accents` |
| `dim_player_league_seasons` | 498 rows; `except all` both ways against the copy: 0 and 0 | task 1's copy |
| `fct_player_category_value` / `fct_player_season_value` / `fct_transaction_impact` rows | 9,860 / 580 / 737 | count |
| each fact, existing columns | `except all` both ways against the copy: 0 and 0 | task 1's copy |
| each fact, `mlbam_player_id` null | 0 rows | count |
| each fact, `mlbam_player_id` equal to its league-season row's | every row | the singular test of R3.4 returns 0 rows |
| platform players with different MLB ids across league-seasons (R2.3) | 0 | the warning test |
| MLB ids shared by two platform players in one league-season | 0 | query |

CI (fixtures; measured on the warehouse the gates built for PR #103, whose branch does
not touch these models):

| Check | Expected | How to verify |
|---|---|---|
| `dim_players` rows | 363 | count |
| by `name_source` | 74 `mlb`, 289 `platform` | group by |
| platform players with no `dim_players` row | 7 (transaction-only, `unresolved`) | anti-join |
| facts' rows | 4,437 / 261 / 11 | count |
| CI `dbt build` | no error; the warnings CI has today, plus R2.3's only if the fixtures trip it | task 1 records "now" |
| tenant isolation | 0 differing pairs | `.agentic/gates` |
