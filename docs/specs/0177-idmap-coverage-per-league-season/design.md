# The id-map coverage test judges each league-season by its share of started players — design

Issue: #177 · Requirements: [requirements.md](requirements.md) · Tasks: [tasks.md](tasks.md)

## Overview

`stg_idmap__covers_started_players` keeps its job, which is to watch the SFBB crosswalk
itself. It changes how it counts. It no longer pools every loaded season against one
threshold. It counts each league-season's started players and how many of them the map
has no row for, and fails when that share is above 5%. On the real warehouse the worst
league-season is 1.87% (C2). An empty or broken map is 100%. A map that loses the rows of more than a
twentieth of a league-season's started players crosses the line, whatever the number of seasons loaded.
Rows of players this league never started are not seen: 2,424 of the map's 3,657 ids (C13). The test stops warning on the
two dozen players the map is missing: they are matched by name, and the resolution test
already warns on any player the fallback cannot match. Four plants prove the failing case, the boundary, the empty map
and that a healthy league-season does not dilute a failing one, on every CI run, because the fixtures hold no uncovered player.
No model changes.

## Claims ledger

Read-only, on `data/warehouse_main_ac0e2ac.duckdb` (`main` at ac0e2ac, built from empty on
2026-10-19; nothing the test reads has changed between ac0e2ac and 4355540), on the SFBB
payload `data/raw/idmap/player_id_map/provider=sfbb/fetched_at=20260926T173654Z/payload.json`,
and on the CI warehouse `dbt/ci.duckdb`. "Started" below is `lineup_slot not in ('BE','IL')`
or the seed's `is_starting_slot`: C11 shows they agree.

| # | Claim | Query (or script) | Result | Run on |
|---|---|---|---|---|
| C1 | Pooled across seasons, the test returns 24 players | the issue's query, without `group by season` | 24 of 1,257 distinct started players | 2026-10-20 |
| C2 | Per league-season, the uncovered share is at most 1.87%. One league is loaded | `select league_id, season, count(distinct espn_player_id), count(distinct case when x.mlbam_player_id is null then espn_player_id end) from stg_espn__roster_entries e left join stg_idmap__players x using (espn_player_id) where lineup_slot not in ('BE','IL') group by all` | league 73677 only. 2018 0/429, 2019 0/407, 2021 0/425, 2022 1/454 (0.22%), 2023 1/450 (0.22%), 2024 8/452 (1.77%), 2025 8/479 (1.67%), 2026 9/481 (1.87%). The per-season counts sum to 27: three players are uncovered in two seasons each | 2026-10-20 |
| C3 | No value is lost: every uncovered player resolves by name | `player_resolution, input_status, count(*), count(distinct platform_player_id)` on `int_fantasy__started_player_days`; `season, player_resolution, count(*)` on `dim_player_league_seasons where not is_transaction_only` | `unambiguous_name`: 281 played + 621 verified-off days (902), 24 players. No `unresolved` row in either relation | 2026-10-20 |
| C4 | The gap is mostly map rows with a blank ESPN id, not late call-ups | Python over the SFBB payload: for each of the 24 names, the rows whose `PLAYERNAME` equals it, with `ESPNID`, `MLBID` | 15 have a row with an MLBAM id and a blank `ESPNID` (e.g. Drew Smith, 2022, MLBAM 622098). 2 have a row under another ESPN id (Austin Adams: map 31660, ESPN 36046. Andrew Morris: map 5266690, ESPN 5007765). 7 have no row by that name, all from 2026 (e.g. Michael Petersen) | 2026-10-20 |
| C5 | There is one map capture, so the in-season lag cannot be measured | `raw.captures where source = 'idmap'`; payload row counts | one capture, `20260926T173654Z`. 3,866 rows, 3,659 with an `ESPNID`. `stg_idmap__players` holds 3,657 | 2026-10-20 |
| C6 | With no map at all, the name fallback alone would still resolve 97–99.8% of started players, so a test of unresolved players cannot guard the map | the crosswalk's `unambiguous_names` CTE rebuilt (`strip_accents` of batting and pitching log names, one MLBAM id per name and season), joined to each season's started players on accent-stripped name and season | resolved by name / started: 2018 420/429, 2019 396/407, 2021 417/425, 2022 446/454, 2023 443/450, 2024 446/452, 2025 472/479, 2026 480/481 | 2026-10-20 |
| C7 | With today's map, the share of an early cut of a season is lower than the full season's. This says nothing about the map as it was early in those seasons (C5) | C2, restricted to `scoring_period <= p` for p in 1, 7, 14, 28, 56, all; 2024–2026 | p ≤ 14: 0 uncovered in each (210–285 started). p = 28: 0.30–0.93%. p = 56: 0.26–1.36%. Full season: 1.67–1.87% | 2026-10-20 |
| C8 | A debut-based proxy for a map frozen a season earlier: 7–13% of a season's started players first appear in the loaded MLB logs that season. Not a bound: a player added to the map late, whatever his debut, is not counted, and a rookie listed before his debut is | started players with a map row, whose earliest season in the loaded MLB game logs (2018–2026) is the league-season's season | 2019 43/407, 2021 55/425, 2022 46/453, 2023 42/449, 2024 38/444, 2025 35/471, 2026 34/472 (7.2%–12.9%) | 2026-10-20 |
| C9 | The CI fixtures hold no uncovered started player | C2 on `dbt/ci.duckdb` | league 111111, 2026: 0 of 260. `stg_idmap__players` 318 rows | 2026-10-20 |
| C10 | The test is in the BigQuery slice | `dbt ls --target ci --selector bigquery_slice --resource-type test` | lists `front_office.stg_idmap__covers_started_players` | 2026-10-20 |
| C11 | The seed's `is_starting_slot` and `lineup_slot not in ('BE','IL')` pick the same entries | count of `stg_espn__roster_entries` with `lineup_slot not in ('BE','IL')`; `is_started` counts of `int_fantasy__roster_days` (which takes it from the seed) | 316,113 entries both ways; 1,257 distinct players | 2026-10-20 |
| C12 | A plant can delete the map rows of a number of started players computed from the fixture, in one DELETE | on `dbt/ci.duckdb`: `started` = distinct `espn_player_id` of `stg_espn__roster_entries` joined to `espn_lineup_slots` where `is_starting_slot`; `pick` = `stg_idmap__players` ids in `started`, `order by espn_player_id limit (select count(*) * 5 // 100 + 1 from started)`; count `pick` and how many are in `started` | 14 picked, all 14 started players. (The first 14 map ids by id, not restricted to started players, hold only 12, so the restriction matters.) DuckDB accepts a scalar subquery in `LIMIT`. `stg_idmap__players` is a view (staging is `+materialized: view`), so a plant materializes it | 2026-10-20 |
| C13 | Most map rows belong to players this league never started | `stg_idmap__players` ids not among started `espn_player_id`s | 2,424 of 3,657 | 2026-10-20 |
| C14 | The uncovered players are regulars of this league's rosters, not obscure ones, and the name fallback picks the MLB player SFBB lists for every one SFBB has | started entries per player (C4's list); `mlbam_player_id` of `dim_player_league_seasons where player_resolution = 'unambiguous_name'` against the SFBB payload's `MLBID` for the same name | started entries: Reed Garrett 160, James McArthur 107, Drew Smith 93, Michael Petersen 85, Alec Marsh 81, Austin Adams 75, Andrew Morris 63; the fewest are DJ Herz and Richard Fitts at 1. All 17 players SFBB lists (blank or other ESPN id) get the same MLBAM id from the fallback as SFBB's `MLBID`; the 7 SFBB lacks cannot be cross-checked | 2026-10-20 |
| C15 | ESPN's roster payload carries no MLB id to join on instead | keys of `teams[].roster.entries[]`, `.playerPoolEntry` and `.playerPoolEntry.player` in a 2019 roster payload | player keys: `active`, `defaultPositionId`, `droppable`, `eligibleSlots`, `firstName`, `fullName`, `gamesPlayedByPosition`, `id`, `injured`, `injuryStatus`, `lastName`, `ownership`, `proTeamId`, `stats`, `universeId`. No external id | 2026-10-20 |

## Alternatives considered

### What the test checks (ADR 0089)

| | A — the crosswalk's coverage (chosen) | B — players unresolved after the fallback |
|---|---|---|
| Sees the map break | yes: an empty map is 100% | barely: with no map, 1–11 unresolved per season (C6) |
| Sees value lost | no; the resolution test does (C3) | yes |
| Overlaps an existing test | no | `dim_player_league_seasons_rostered_players_are_resolved` already warns on exactly this |

**A** keeps the only check on the map. **B** would duplicate the resolution test, and the
name fallback hides a broken map from it. The fallback is good enough that losing the
whole map would show as a warning on 1–11 players a season (C6), the ones whose names two
MLB players share.

### How it counts (ADR 0089)

| | A — share per league-season (chosen) | B — count per league-season | C — share pooled across the warehouse | D — a check on the map alone |
|---|---|---|---|---|
| Loading a season moves it toward failing | no | no | no, but a broken season is diluted by healthy ones | no |
| Fits a league of another size | yes | no: a deeper league starts more players | yes | yes |
| Sees "the map no longer covers our players" | yes | yes | yes, diluted | no: a map with plenty of rows could still miss ours |
| Threshold rests on | this data's shares (C2) | this league's size | this data's shares | SFBB's file size (3,657 rows, C5) |

**A** answers the issue's question directly: a league-season is judged on its own players,
so the eight seasons loaded today and the ninth tomorrow cannot add up. It also passes the
tenant-isolation gate by construction (R1.3).

**B** works for this league, but a count of 25 means something different in a 20-team
league than in a 10-team one. The project prefers rules that hold across leagues.

**C** fails only if the map breaks badly across most seasons. A map that drops one
season's rookies (C8's case) would be hidden behind seven healthy seasons.

**D**, for example "the map has at least 3,000 rows with an ESPN id", catches an empty map
or a renamed column. It cannot see the map drifting away from the players this league
starts, and its threshold describes SFBB's file, not this project's needs.

### The threshold (ADR 0089)

| | 3% | **5% (chosen)** | 10% |
|---|---|---|---|
| Headroom over the worst real share, 1.87% (C2) | 1.6× (one bad season away: 15 of 481 is 3.1%) | 2.7× | 5.3× |
| An empty or column-broken map (100%) | fails | fails | fails |
| A map frozen a season earlier (debut proxy 7–13%, C8) | likely fails | fails if it misses more than 24 of 481 | may pass |
| Players needed to cross it at 2026's 481 | 15 | 25 | 49 |

**5%** is chosen. The real gap does not close after a season (C4) and has grown from 0.22% to
1.87% (C2), so it leaves room for that growth for a few seasons, and still fails well below
any breakage of the map itself. At **3%**, an ordinary bad season fails the build, which is the
problem this issue is about. At **10%**, a map as stale as C8's proxy could pass. C8 is a proxy, not a bound, so where a frozen map really falls is unknown (*Open questions*).

### The warning (ADR 0089)

| | (a) no warning (chosen) | (b) warn on any uncovered player | (c) warn above a lower share |
|---|---|---|---|
| Real build today | silent | warns: 5 of 8 league-seasons, 27 player-seasons | silent at e.g. 2.5% |
| Shows the name-matched players | through `player_resolution` on the marts | in the test's output | only once drifting |
| Cost | none | a warning on every build, so new warnings are easier to miss | a second threshold with no evidence behind it |

**(a)** is chosen. The 24 players are matched by name, and `player_resolution =
'unambiguous_name'` already marks them in `dim_player_league_seasons`. A player the
fallback cannot match warns through the resolution test. A warning that fires on every
build teaches people to stop reading warnings.

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0089](../../adr/0089-the-id-map-coverage-test-fails-on-a-league-seasons-share-of-uncovered-started-players.md) | The id-map coverage test guards the map, per league-season, failing above 5% of started players, with no warning below. Chosen by the owner, 2026-10-20 | proposed (accepted on approval of this spec) |

## Detailed design

### `dbt/tests/stg_idmap__covers_started_players.sql`

The name stays, so the plant file and the history refer to the same test.

- **Grain of the result:** one row per (`league_id`, `season`) whose share is over the
  limit. Columns: `league_id`, `season`, `started_players`, `uncovered_players`.
- **Started:** a roster entry whose `lineup_slot_id` is a scoring slot in the
  `espn_lineup_slots` seed (`is_starting_slot`), as `int_fantasy__roster_days` does. Today
  this picks the same entries as the string test it replaces (C11). A slot a new league
  adds is then judged by the seed, not by its name.
- **Uncovered:** no row in `stg_idmap__players` for the `espn_player_id`. That model drops
  rows missing either id and is unique on `espn_player_id`, so a left join counts each
  player once.
- **Config:** `severity='error'`, with dbt's default thresholds: any row fails. The
  `warn_if` / `error_if` pair goes, because the rows are now league-seasons over the
  limit, not players.

A **singular test** in dbt is a SQL file under `dbt/tests/`. dbt runs it, and every row it
returns is a failure. `severity`, `warn_if` and `error_if` turn the row count into a pass, a
warning or an error. The shape, in SQL both warehouses accept (C10, R4.1):

```sql
{{ config(severity='error') }}

with started_players as (

    select distinct
        entries.league_id,
        entries.season,
        entries.espn_player_id
    from {{ ref('stg_espn__roster_entries') }} as entries
    inner join {{ ref('espn_lineup_slots') }} as slots
        on slots.lineup_slot_id = entries.lineup_slot_id
    where slots.is_starting_slot

),

coverage as (

    select
        started_players.league_id,
        started_players.season,
        count(*) as started_players,
        count(case when crosswalk.espn_player_id is null then 1 end) as uncovered_players
    from started_players
    left join {{ ref('stg_idmap__players') }} as crosswalk
        on crosswalk.espn_player_id = started_players.espn_player_id
    group by started_players.league_id, started_players.season

)

select
    league_id,
    season,
    started_players,
    uncovered_players
from coverage
where 100 * uncovered_players > 5 * started_players
```

The header comment says (R2.3):
- the test guards the map, not values, and why the fallback hides a broken map (C6);
- the limit and the evidence behind it (C2, C8);
- where the current gap comes from (C4);
- that unresolved players are the resolution test's job.

### `dbt/plants/stg_idmap__covers_started_players.yml`

Each plant materializes `staging.stg_idmap__players` (a view, C12) and deletes from it. The selection is among started players, not map ids (C12). The
number deleted is computed from the fixture's started players, so the plants keep holding the boundary if the
fixtures are regenerated with another count. With 260 started, 5% is 13 players.

| Plant | Deletes the map rows of | Expect |
|---|---|---|
| `map_misses_more_than_a_twentieth` | `started * 5 // 100 + 1` started players (14) | `{status: fail, failures: 1}` |
| `map_misses_exactly_a_twentieth` | `started * 5 // 100` started players (13), and `started * 5 % 100 = 0` holds for 260 | `pass` |
| `map_is_empty` | every row | `{status: fail, failures: 1}` |
| `a_healthy_league_season_does_not_dilute_another` | as the first plant (14), then inserts into the materialized `staging.stg_espn__roster_entries` a copy of the fixture's started entries of still-covered players under another `league_id` | `{status: fail, failures: 1}`: only league 111111. A pooled count would see 14 of 506 (2.8%) and pass |

The rows deleted are chosen by `espn_player_id` order among started players, so the
choice is deterministic. If the fixture's started count changes so that 5% is not a whole
number, the exact-limit plant still deletes the most players that pass, `floor(5%)`. The
other two do not depend on the count.

### `dbt/models/intermediate/fantasy/int_fantasy__roster_days.sql`

Its header says the fallback covers "the nine players the crosswalk test warns about". The test no
longer warns (option (a)), so the clause is reworded to name the players matched by
name. Comment only; the model's SQL does not change.

## Test strategy

| Requirement | Test | Catches |
|---|---|---|
| R1.1, R2.1 | plant `map_misses_more_than_a_twentieth` | a test that no longer fails on a league-season over the limit, or counts at the wrong grain (failures ≠ 1) |
| R1.2, R2.2 | plant `map_misses_exactly_a_twentieth` | an off-by-one at the boundary (`>=` for `>`), or a division that rounds |
| R2.1 (map broken) | plant `map_is_empty` | the issue's "it must still fail if the map itself breaks" |
| R1.3 | plant `a_healthy_league_season_does_not_dilute_another` | a count pooled across league-seasons, in which healthy ones dilute a failing one. (The tenant-isolation gate compares model relations, not this test's rows, so it does not hold R1.3.) |
| R2.2 | real build: `PASS`, and no warning | a test still warning on the lagging players |
| R4.1 | `test_dbt_portable_sql_rule.py`; `dbt compile --target bq` of the test | a DuckDB-only construct |
| R2.3 | review | a header that no longer matches the data |

## Risks

- **SFBB stops updating its file.** A frozen map misses at most 7–13% of a season (C8),
  but SFBB may list players before they debut, so the real miss could be under 5%. The
  test would then pass while the gap grows. *Medium likelihood over years, low impact
  (the fallback resolves most players, C6).* Accepted. The idmap freshness check sees only
  a stale capture, not a stale file.
- **A deeper or prospect-heavy league starts more players SFBB lacks.** The test would
  fail on a real but harmless gap. *Low likelihood.* Accepted: the failure names the
  league-season, and the limit can be revisited with that league's numbers.
- **The exact-limit plant is exactly at the limit only while 5% of the fixture's started
  count is whole.** It is for 260. With another count it deletes `floor(5%)` players and
  still expects `pass`, but tests a point just under the limit. *Low impact.* Accepted;
  the plant's `why` says so.

- **An early-season map may miss more than 5% of the season's starters at that point.** C7 uses today's map, and no dated early-season map exists (C5). The build would then fail on a gap SFBB later closes. *Unknown likelihood, low impact: a failed build names the league-season, and nothing is lost.* Accepted; the first early-season build of 2027 is the evidence.

## Open questions

- How far the map lags inside a season. One capture exists (C5). C7 is measured with
  today's map, so it bounds the early-season share from below. Resolved only by keeping
  dated map captures through a season. Not needed to decide the limit.
- What a map frozen a season earlier would really miss. C8 is a debut-based proxy, since
  no older capture exists. Not needed to decide the limit, but the limit's claim about a
  frozen map rests on it.

## Review log

| Source | Finding | Resolution |
|---|---|---|
| design-review | F1: C8 is not a bound on what a frozen map misses | C8 relabelled a debut-based proxy; the threshold table and the ADR say so; moved to *Open questions* |
| design-review | F2: "loses a twentieth of its rows" is not what a started-player coverage test sees | reworded to started players' rows; C13 records that 2,424 of 3,657 map ids are never started; goal and ADR reworded |
| design-review | F3: the tenant-isolation gate does not compare singular-test rows, so it does not hold R1.3 | added plant `a_healthy_league_season_does_not_dilute_another` (R3.4); R1.3 no longer cites the gate |
| design-review | F4: C12's query picked map ids, 12 of 14 started | C12 rerun with the started-player selection: 14 of 14; plants pick among started players |
| design-review | F5: C7 uses today's map, so it is no evidence about early-season maps | C7 reworded; the possible early-season failure added under *Risks* |

## Amendments
