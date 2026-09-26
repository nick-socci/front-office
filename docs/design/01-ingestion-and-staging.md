# 01 — Ingestion → DuckDB → dbt staging → CI

**Date:** 2026-09-20 · **Status:** Built and merged as PRs 1–6. Kept as written.
**Context:** [`00-project-origin.md`](00-project-origin.md) holds the overall plan. This spec covers
the first of several sub-projects. Later ones are marts and the platform-neutral `int_*` layer
([`02-intermediate-and-marts.md`](02-intermediate-and-marts.md)), orchestration and deployment, the
dashboard, and the BigQuery migration. Each gets its own doc.

## Decisions made

| Decision | Choice |
|---|---|
| Project name | **Front Office**. Repo/CLI `front-office`, Python package `front_office` |
| Data mode | **Backfill-first**: build on the full 2026 season. Daily/live runs are designed but first exercised in the 2027 season |
| League | Private ESPN league, `H2H_MOST_CATEGORIES`, 12 teams, 24 matchup periods, 180 scoring periods, 17 scored stat IDs (not standard 5x5) |
| Multi-league future | Data model is league-agnostic (`league_id` + `season` on every league row; scoring rules as data). Operations are single-user. No portal, auth, or per-user credential storage in this sub-project |
| Platforms | ESPN only, with a thin seam: ESPN specifics live only in `ingestion/.../espn/` and `stg_espn__*` models |
| Warehouse | DuckDB now; migrate to BigQuery before calling v1 done (separate sub-project) |
| Ingestion approach | ELT: land raw JSON unchanged → load as-is into one raw table → all parsing in dbt |
| Scope | Full slice below, accepted at a revised whole-project estimate of ~35–45 hrs |

## ESPN feasibility (verified by spike, 2026-09-20)

A throwaway probe (`spikes/`, gitignored) confirmed the following for this league:
- Historical rosters: `mRoster&scoringPeriodId=N` returns the roster as of period N. All 12 teams
  differ between period 10 and 180.
- Matchup results by category (WIN/LOSS/TIE per stat ID) for past matchup periods, **including
  non-scored component stats** (e.g. stat 0 = AB 197, stat 1 = H 53, stat 2 = AVG .269). Ratio
  categories can therefore be rebuilt from their components.
- Transaction log: 485 activities from 2026-03-02 to 2026-09-20 (full season).
- A safety snapshot (183 files, ~650 MB) sits in `data/raw/espn/`. It's a backup only, not a pipeline
  input, and its layout (`roster_matchup/`) intentionally differs from the real one.
- The `mMatchupScore`/`mScoreboard` views return the whole season's schedule on every call, which
  is why the snapshot is ~3.5 MB per period. Real ingestion fetches matchups once per run.

**Action items (time-sensitive):**
1. **Re-run the ESPN snapshot after the league completes** (settings, matchups, period 180 rosters,
   transactions). At the time of the spike, period 180 was both the latest and the final period, and a
   transaction happened that day, so the final results are probably not in the snapshot yet. Do this
   before the cookies expire or ESPN rolls the league over to 2027.
2. **Back up `data/raw/espn/` somewhere private.** It holds private league data and can't be
   re-fetched after the rollover. Destination still to be chosen (private GCS bucket or offline archive).

## Repo layout

```
pyproject.toml              # uv-managed; ruff, mypy (strict), pytest config
ingestion/                  # renamed from data_generator/
  src/front_office/
    http_client.py          # the only code that makes network calls
    landing.py              # landing-zone paths, atomic writes, metadata sidecars
    mlb/                    # MLB Stats API extractors
    espn/                   # ESPN extractors; the only code that reads ESPN credentials
    idmap/                  # player ID crosswalk extractor
    load.py                 # landing zone -> raw.api_responses
    cli.py                  # Typer CLI: `front-office backfill mlb --season 2026`, etc.
  tests/
scripts/make_fixtures.py    # builds anonymized CI fixtures from real landed data
fixtures/landing/           # committed, anonymized fixture landing set
dbt/                        # dbt-duckdb project
data/                       # gitignored: raw/ landing zone + warehouse.duckdb
spikes/                     # gitignored throwaway notebooks/scripts
.github/workflows/ci.yml
```

`orchestration/` and `dashboard/` stay empty; they belong to later sub-projects.

## Ingestion

### Components
- **`http_client`**: an `httpx` client with minimum spacing between requests per source (MLB ~2 req/s,
  ESPN ≥1.5 s between requests), exponential-backoff retries on 429/5xx (max 5 attempts), and a
  descriptive User-Agent. **An ESPN 401/403 fails fast** with "ESPN cookies expired — refresh `.env`".
  Everything else uses this client; tests inject `httpx.MockTransport`.
- **`landing`**: path convention `data/raw/{source}/{endpoint}/{partition keys}/{id or fetched_at}.json`
  plus a metadata sidecar (URL, canonical params, `fetched_at`). Writes go to a temp file and then an
  atomic rename, so a crash never leaves a partial file.
- **Extractors**: each one knows its endpoint, how to enumerate work items, and its **mode**.
- **`load`**: reads the landing zone into `raw.api_responses`. Idempotent.
- **`cli`**: a thin Typer wrapper. It is also the future entry point for Cloud Run and Dagster.

Credentials (`ESPN_S2`, `SWID`, `LEAGUE_ID`) are read from `.env` inside `espn/` only. They are
never written to landing files, sidecars, or logs.

### Endpoints and modes

| Source | Endpoint | Mode |
|---|---|---|
| MLB | `schedule?sportId=1&season=…&gameType=R` | snapshot |
| MLB | `game/{game_pk}/boxscore` | immutable after a **7-day settle window** past Final |
| ESPN | settings (`mSettings` + `mStatus`) | snapshot |
| ESPN | teams (`mTeam`) | snapshot |
| ESPN | rosters (`mRoster`, `scoringPeriodId=N`) | immutable once **period N has actually ended** (checked against league status, not just `N <= latest`) |
| ESPN | matchups (`mMatchupScore` + `mScoreboard`, once per run) | snapshot |
| ESPN | transactions (`communication/`, `kona_league_communication`) | snapshot |
| ID map | SFBB player ID map CSV (ESPN ID ↔ MLBAM ID); confirm it's still published before building | snapshot |

- **Snapshot**: written as a new file with its `fetched_at` on every run.
- **Immutable**: skipped if already landed, unless `--refresh` is passed.
- **Settle window**: official scoring changes can alter a boxscore days after the game. Boxscores are
  re-fetched on every run until 7 days after Final. This doesn't matter for the 2026 backfill, which
  runs after the season; it matters for 2027 daily runs. Suspended/resumed games (one `game_pk`
  spanning two dates) take the date from the schedule's official game date.

### Backfill sequence
- `front-office backfill mlb --season 2026`: schedule → keep `gameType=R` games that are Final →
  boxscores (~2,430 games, ~20 min).
- `front-office backfill espn --season 2026`: settings → teams → matchups → rosters for periods
  1..last completed → transactions.
- `front-office backfill idmap`, then `front-office load`.

### Error handling
- Each work item fails independently: the failure is logged, the run continues, and a summary prints at the end.
- The exit code is nonzero if any item failed. A rerun fetches only the missing immutable items.
- ESPN auth failure aborts the whole ESPN run immediately.

## Warehouse raw layer

A single table, `raw.api_responses`:

| Column | Notes |
|---|---|
| `source` | `mlb` / `espn` / `idmap` |
| `endpoint` | e.g. `boxscore`, `roster` |
| `request_key` | canonical, sorted request params |
| `fetched_at` | UTC timestamp |
| `payload` | JSON (CSV rows for the ID map are loaded as JSON objects) |
| `file_path` | kept only to trace a row back to its landing file; **not** part of the key |

The natural key is `(source, endpoint, request_key, fetched_at)`. Whether to split into one raw table
per endpoint or partition by `endpoint` is left to the BigQuery migration.

## dbt staging layer

**Project:** `dbt-duckdb`. Targets: `dev` (`data/warehouse.duckdb`) and `ci` (in-memory, built from
`fixtures/landing/`). Packages: `dbt_utils`.

**Source freshness** is configured using `fetched_at` but not enforced in CI (fixtures are stale by
design). It becomes meaningful when daily runs start in 2027.

**Macros:**
- `json_*` helpers (scalar extraction, array unnesting), **DuckDB-only for now**. They keep dialect
  details out of models, so the BigQuery migration only touches the macros (adding the
  `adapter.dispatch` variants then).
- A dedupe helper that keeps the latest `fetched_at` per **entity key**, using `QUALIFY` (works on
  both DuckDB and BigQuery). Dedupe happens at the entity grain inside each model, never per
  `request_key`, because chunked requests can return overlapping entities.

**Models.** The JSON-heavy models are materialized as **tables**; the rest are views.

| Model | Grain (dedupe key) | Notes |
|---|---|---|
| `stg_mlb__games` | `game_pk` | date, teams, status, `game_type`; regular season only |
| `stg_mlb__batting_game_logs` | `(game_pk, mlbam_player_id)` | **component counts only** (AB, H, 2B, 3B, HR, R, RBI, BB, SO, SB, CS, HBP, SF…); table |
| `stg_mlb__pitching_game_logs` | `(game_pk, mlbam_player_id)` | components only; innings stored as **`outs_recorded`** ("6.1" → 19); table |
| `stg_espn__league_settings` | `(league_id, season)` | scoring type, sizes, period counts |
| `stg_espn__scoring_categories` | `(league_id, season, stat_id)` | includes `is_reverse` (ERA/WHIP-style lower-is-better) |
| `stg_espn__scoring_periods` | `(league_id, season, scoring_period)` | period → calendar date, **US/Eastern day boundary** |
| `stg_espn__teams` | `(league_id, season, team_id)` | names aliased when `anonymize` is true |
| `stg_espn__roster_entries` | `(league_id, season, scoring_period, team_id, espn_player_id)` | lineup slot; table |
| `stg_espn__matchups` | `(league_id, season, matchup_period, home_team_id, away_team_id)` | winner, category W/L/T totals |
| `stg_espn__matchup_category_results` | `(league_id, season, matchup_period, team_id, stat_id)` | per-category score and WIN/LOSS/TIE; includes non-scored component stats |
| `stg_espn__transactions` | `(league_id, season, transaction_id)` | type, team, player, date |
| `stg_idmap__players` | `espn_player_id` | → `mlbam_player_id` |

**Rules that apply to every model:** rate stats (AVG, ERA, WHIP, K/9…) are never carried in
staging. They're rebuilt from components downstream.

**Seeds:** `espn_stat_ids.csv` and `espn_lineup_slots.csv`, generated from `espn-api`'s baseball
constants (confirm the license) and cross-checked against the spike (0=AB, 1=H, 2=AVG).

**Privacy:** staging never selects ESPN member or owner IDs, or owner names. When
`var('anonymize')` is true (CI, anything public), team names and abbreviations become stable aliases
(`Team 07`). Locally they default to real names.

## Testing

**Python (pytest):**
- `http_client`: retry/backoff on 429/5xx and stopping after 5 attempts; fail-fast on ESPN 401/403;
  per-source spacing between requests. All via `httpx.MockTransport`, with no network.
- `landing`: path construction per endpoint; a crash between the temp write and the rename leaves no
  partial file.
- Mode logic: a game Final <7 days ago is re-fetched and one ≥7 days ago is skipped; a scoring period
  still in progress is re-fetched.
- `load`: loading the same files twice yields the same row count.
- Privacy check: no fixture file contains a `members` key or a GUID-shaped string.

**dbt:**
- Generic tests: `not_null` + unique (`dbt_utils.unique_combination_of_columns` for composite keys)
  on every grain above; `relationships` for roster → teams, roster → scoring periods, and game logs →
  games.
- Range tests: `dbt_utils.accepted_range` / `expression_is_true`, e.g. `outs_recorded >= 0` and
  `hits <= at_bats`.
- Unit tests (dbt ≥ 1.8): innings → outs, entity-grain dedupe, scoring period → date.
- Custom SQL tests: every scored `stat_id` in settings exists in the stat seed; consecutive scoring
  periods map to consecutive dates.
- An ID-crosswalk quality test: the share of rostered players with no MLBAM match stays below a
  threshold (warn, not error, at first).

**Fixtures:** `scripts/make_fixtures.py` **rebuilds minimal payloads from an allowlist** of the fields
staging actually reads. It never scrubs a full payload, because a scrub list would eventually miss a
name. The fixture set is one consistent slice: one scoring period, that date's MLB games and their
boxscores, and the matching rosters, teams, settings, and ID-map rows. Committed and regenerated only
on purpose.

## CI (GitHub Actions: every push and PR)

`uv sync` → `ruff check` + `ruff format --check` → `mypy --strict` (on `ingestion/src`) → `pytest` →
load `fixtures/landing/` into DuckDB → `dbt build --target ci` (seeds, models, generic tests, unit tests).
CI status badge goes in the README. Pre-commit is optional. SQL linting (sqlfluff) is on the roadmap,
not in scope here.

## Build order (dbt learning curve)

Each step introduces the next dbt concept:
1. Python scaffold, `http_client`, `landing`, MLB schedule extractor, `load`, CI with ruff/mypy/pytest.
2. `stg_mlb__games`: sources, first model, generic tests, `dbt build` in CI against fixtures.
3. Boxscore extractor, then the batting/pitching game logs: table materialization, unit tests, range tests.
4. ESPN settings/teams/rosters extractors, then their staging models: seeds, macros, custom SQL tests,
   anonymization.
5. `stg_espn__scoring_periods`: the join that proves the slice works.
6. Matchups, transactions, ID map.

## Definition of done

1. `front-office backfill …` + `load` land the full 2026 season into `data/warehouse.duckdb`.
2. `dbt build` passes locally on the full season.
3. CI is green on `main`, running the fixture build.
4. One SQL query over staging models answers: *"who was on team X's roster on date D, and what did
   each of them do in MLB that day?"*

## Out of scope (later sub-projects)

Platform-neutral `int_*` models and marts · Dagster definitions · Cloud Scheduler/Cloud Run · the
BigQuery migration (including the BigQuery macro variants) · Streamlit dashboard · GUMBO live feed ·
portal/auth/multi-user credentials · other fantasy platforms.

**Roadmap notes:** the MLB Stats API carries a non-commercial-use notice. That's fine for a personal
tool, but revisit it before any multi-user portal becomes more than a hobby. Storing other users'
ESPN cookies is the core security problem any portal must solve.
