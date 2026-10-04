# League and season identity through raw storage and every model — requirements

Issue: #28 · Tier: L · Status: draft

## Problem

The warehouse can hold exactly one ESPN league-season, and nothing stops a second from
being loaded on top of it. Review finding
[R2](../../reviews/2026-09-27-code-review.md#r2--p1-espn-identity-is-lost-at-both-loading-and-staging)
set the deadline: before any second league or season is loaded, including an older one.
#57 (historical seasons) now waits on it. Measured on 2026-10-04
([design.md](design.md#evidence)):

- **The raw key drops the league and season.** `raw.api_responses` is keyed by (source,
  endpoint, request parameters, fetch time). ESPN's league and season are in the URL
  path, not the parameters. Four landed settings responses, two leagues by two seasons
  in the same second, load as **one** row; the other three are discarded without error.
- **"Latest" is global.** `fo_espn_latest` takes the single newest response per endpoint
  (per scoring period for rosters), so a 2027 capture would replace 2026 in every staging
  model that uses it.
- **Five models carry no league or season at all**: `stg_espn__transactions`,
  `int_fantasy__transactions`, `int_fantasy__replacement_levels`, `dim_players`,
  `fct_transaction_impact`. Others assume one league in passing: the replacement pool's
  size is a count of every team loaded, the transaction windows take the first and last
  scoring date of everything loaded, and every league's scoring periods run to the
  longest season's end.

## Goals

- Any number of ESPN leagues and seasons can be landed, loaded and built together, and
  each one's models are exactly what they would be if it were built alone.
- A capture is never silently discarded at load.
- The 2026 numbers do not change.

## No-gos

- **No second league or season is fetched or loaded here.** That is #57, and needs the
  owner's go-ahead and credentials.
- **No change to the landing zone**: its layout, its sidecar format, and every landed
  file stay as they are. The raw table is rebuilt from them.
- **No change to any 2026 number.** Every existing column of every model is identical
  after the change. Models only gain columns, with one exception: five columns of
  `dim_players` move, with the same values, to the new `dim_player_league_seasons`
  (ADR 0012).
- **Not R1, R3 or R4** (#27, #29, #30): capture timing, orphan repair and settle windows
  are separate work. No sub-second timestamps.
- **No second fantasy platform.** `platform` stays `'espn'`.
- **The current warehouse is not replaced or deleted by an agent.** The rebuilt one sits
  beside it until the owner swaps them. The NAS backup is not touched.
- **No tolerance widening** and no test weakened to make a build pass.

## Rabbit holes

- *A general multi-tenant framework* → identity is two columns carried through joins,
  and one check that proves isolation. No tenant registry, no per-tenant schemas.
- *Hunting every single-league assumption by reading* → the isolation check finds them:
  any model that differs between a combined build and a build of one league-season
  alone is named by it.
- *Building out the player dimension* → `dim_players` keeps only what is true of a player
  everywhere, and one new model holds what is true of him in a league-season
  ([ADR 0012](../../adr/0012-players-have-a-conformed-dimension-and-a-league-season-table.md)). No
  history of name changes, no MLB team, no career table.
- *Realistic second-league fixtures* → the extra tenants are relabelled copies of the
  committed fixture. They prove isolation, not baseball.

## Requirements

### R1. Raw identity

- R1.1 THE SYSTEM SHALL store on every row of `raw.api_responses` the request path and
  the landing partitions of the capture, taken from its sidecar.
- R1.2 THE SYSTEM SHALL derive the request path from the sidecar's URL as the URL's path
  with no scheme, host or query string and no trailing slash, by one function used
  wherever the path is needed.
- R1.3 THE SYSTEM SHALL key `raw.api_responses` by source, endpoint, request path,
  request parameters and fetch time.
- R1.4 IF two landed captures have the same key THEN THE SYSTEM SHALL fail the load,
  naming both files, and insert nothing from that run.
- R1.5 IF the warehouse holds a `raw.api_responses` without these columns THEN THE SYSTEM
  SHALL fail the load with a message saying to rebuild into a new file, and change
  nothing.
- R1.6 THE SYSTEM SHALL compare landed captures with loaded rows on the full key in
  `front-office audit`.
- R1.7 WHEN the same capture is loaded twice THE SYSTEM SHALL insert it once.

### R2. Latest response per league and season

- R2.1 THE SYSTEM SHALL choose the latest ESPN response per endpoint within each league
  and season, and within each scoring period where the endpoint has one.
- R2.2 THE SYSTEM SHALL take the transaction log of each league and season from the
  pages of that league-season's own newest run.
- R2.3 IF an ESPN payload names a league or season that differs from the partitions it
  was landed under THEN THE SYSTEM SHALL fail the build.

### R3. Staging

- R3.1 THE SYSTEM SHALL expose `league_id` and `season` on `stg_espn__transactions`, from
  the landing partitions, and deduplicate messages within a league and season.
- R3.2 THE SYSTEM SHALL generate each league-season's scoring periods from 1 to its own
  final scoring period.
- R3.3 THE SYSTEM SHALL test uniqueness of every ESPN staging model on a key that
  includes league and season.

### R4. Intermediate and marts

- R4.1 THE SYSTEM SHALL carry `league_id` and `season` on `int_fantasy__transactions`,
  `int_fantasy__replacement_levels` and `fct_transaction_impact`, as part of each one's
  key.
- R4.11 THE SYSTEM SHALL resolve a fantasy player to an MLBAM id within each league and
  season: from the id map by id, or failing that by a name match that uses the name on
  his latest roster snapshot of that league-season and counts a name as unambiguous when
  it belongs to exactly one MLB player who appeared in that MLB season.
- R4.12 THE SYSTEM SHALL take the MLBAM id used by every league-season model (roster
  days, started days, player value, transaction impact) from that league-season's own
  resolution.
- R4.8 THE SYSTEM SHALL provide `dim_player_league_seasons` with one row per player per
  league and season in which he was rostered or transacted, holding his MLBAM id and how
  it was resolved in that league-season, his default position, replacement group, first
  and last rostered dates and whether he appears only in that league-season's
  transaction log.
- R4.7 THE SYSTEM SHALL keep `dim_players` at one row per platform player id, across
  every league and season loaded, holding the MLBAM id, resolution and name of his
  latest league-season, as a reference and not as an input to any league-season number.
- R4.9 THE SYSTEM SHALL fail the build if `dim_players` and `dim_player_league_seasons`
  do not hold the same players, or if a `dim_players` row differs from the league-season
  row it is taken from.
- R4.10 WHEN a rostered player has no MLBAM id in a league-season THE SYSTEM SHALL warn
  on every build, naming him, without failing.
- R4.2 THE SYSTEM SHALL form each league-season's replacement pools from the players
  unrostered in that league on that league's scoring dates, sized by that league's own
  number of teams.
- R4.3 THE SYSTEM SHALL bound a transaction's window by the first and last scoring date
  of its own league and season.
- R4.4 THE SYSTEM SHALL join league-scoped relations on league and season wherever both
  sides carry them.
- R4.6 THE SYSTEM SHALL derive anything a league-season's row takes from MLB data from
  that season's MLB data only.
- R4.5 THE SYSTEM SHALL leave MLB and id-map models, which describe no league, without
  league columns.

### R5. Proof of isolation

- R5.1 THE SYSTEM SHALL keep a committed fixture landing zone of two leagues by two
  seasons, in which captures of different leagues share fetch timestamps, the two seasons
  have different lengths, and at least one player is spelled differently in the two
  leagues, generated from the existing fixture by script.
- R5.2 THE SYSTEM SHALL hold that fixture to the same privacy test as the existing one.
- R5.3 THE SYSTEM SHALL fail the gates if any model's rows for a league-season in the
  combined build differ, as a multiset, from that model's rows when that league-season is
  built alone with only its own season's MLB data; or if a model without league columns
  lacks a row the single build has; or if the two builds do not hold the same models.
  `dim_players` alone is exempt from the row comparison, because it is defined over
  everything loaded; it is held to R4.9 instead.
- R5.4 THE SYSTEM SHALL fail the gates if four captures that differ only in league or
  season, fetched in the same second, do not load as four rows.

### R6. Rebuilding the real warehouse

- R6.1 THE SYSTEM SHALL provide a comparison of two warehouses that reports any model
  present in only one, and per model any difference in row count or, as multisets, in the
  values of the columns they share.
- R6.2 WHEN the real landing zone is rebuilt into a new warehouse file THE SYSTEM SHALL
  show no difference from the current warehouse in any shared column of any model.

## Expected values

Real season, `data/raw/` and `data/warehouse.duckdb` as of 2026-10-04.

| Check | Expected | How to verify |
|---|---|---|
| Today's collision | 4 landed settings responses (2 leagues × 2 seasons, one second) load as 1 row | reproduced; becomes the R5.4 test, expecting 4 |
| Committed sidecars | 2,688, every one with `url`, `partitions`, `request_key`, `fetched_at` | scan of `data/raw/` |
| Raw rows after rebuild | 2,688 = settings 3, teams 3, roster 180, matchups 2, transactions 3, schedule 2, boxscore 2,494, id map 1 | group by source, endpoint |
| Distinct keys | 2,688 under the new key, 0 collisions | group by the key |
| Request paths | one per ESPN league-season (plus `/communication` for transactions); `/api/v1/schedule`; one per game for boxscores; `/PLAYERIDMAPCSV` | distinct `request_path` |
| Payloads with no sidecar | 201, still skipped with a warning (#21) | loader log |
| Real warehouse comparison | 0 relations with a difference in a shared column; 39 relations compared; one new relation (`dim_player_league_seasons`); `dim_players` reported as having 5 fewer columns; `int_mlb__player_game_days` one more (`season`) | R6.1 comparison |
| `stg_espn__transactions` | 737 rows, `league_id` and `season` never null, one league-season | query |
| `int_fantasy__replacement_levels` | 48 rows, one league-season | query |
| `dim_players` | 498 rows, key unchanged; `mlbam_player_id`, `player_resolution`, `player_name` identical to today | R6.1 comparison |
| `dim_player_league_seasons` | 498 rows, one league-season; its seven attribute columns (`mlbam_player_id`, `player_resolution` and the five moved ones) identical to today's `dim_players` columns of the same names, player for player | query joining the old `dim_players` |
| Resolution | 489 by id map, 9 by name, 0 unresolved; `int_fantasy__roster_days` 55,653 rows with `mlbam_player_id` and `player_resolution` unchanged on every row | R6.1 comparison |
| Players matched by name | 9 of 498 (`unambiguous_name`), 338 roster days; already reported by the existing warning `stg_idmap__covers_started_players` | query; existing test |
| Rostered players unresolved | 0, so the new warning returns no rows on 2026 | R4.10 test |
| Combined fixture, the conformed dimension | the player spelled differently in the two leagues has one `dim_players` row; the isolation check still reports 0 differences | R5.3 check; R4.9 test |
| `fct_transaction_impact` | 737 rows; `total_value` sums unchanged (221.09 / 457.47 / 170.37 / 451.72) | query |
| Combined fixture, raw | 4 league-seasons; no capture dropped; captures of the two leagues share every ESPN fetch timestamp | R5.3 / R5.4 |
| Combined fixture, isolation | 0 differing rows in any model for any of the 4 league-seasons | R5.3 check |
| Combined fixture, season length | the 2027 league-seasons have 1 scoring period each, the 2026 ones 2 | query on `stg_espn__scoring_periods` |
