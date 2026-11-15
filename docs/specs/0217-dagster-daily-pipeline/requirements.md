# The daily pipeline as Dagster assets — requirements

Issue: #217 · Tier: M · Status: draft

## Problem

Nothing runs Front Office on a schedule, and the pipeline's order (fetch, upload or load, build,
freshness) exists only in the owner's head and in README prose. Spec 0216 decided where it runs
(`mothership`, ADR 0126) and what Dagster is there: the description and the scheduler (ADR 0122).
#218 deploys and schedules it, #219 alerts on it, #220 rehearses it. All three need the definitions
to exist once, so that what runs in production is what `dagster dev` shows on the laptop. Spec 0216
handed over five things to settle here: the asset grain, dbt through `dagster-dbt` (whose 0.29.28
raised `KeyError` on the real manifest), what a failed step does, which season a run fetches, and
the running-season steps (its F5).

## Goals

- The daily pipeline is one Dagster code location in the repository: assets, one job, and the
  settings that choose the warehouse and the season.
- `dagster dev` shows the pipeline with its lineage into the dbt models, and one materialization of
  everything runs green against the real season on the laptop (the issue's "done when").
- A failed fetch is reported without leaving BigQuery a day stale for the other feed.
- The memory of the production processes is measured again with these definitions (0216 R6.3).

## No-gos

- Provisioning the schedule, the container image, the host's services, the pull to the NAS (#218).
- Alerting (#219), and rehearsing a skipped day or the rollover (#220). This spec defines the
  `fetch_complete` check #219 reads; it sends nothing.
- Changing what any CLI command fetches. A CLI change this spec finds it needs goes back to the
  owner first.
- Dagster Cloud, Postgres storage, a run queue, separate code servers (0216's rabbit hole): the
  default instance with SQLite storage, one code location.
- Intraday refresh (owner, 2026-11-03).

## Rabbit holes

- Modelling each endpoint as an asset → one asset per CLI command (ADR 0127).
- Making the dbt models' lineage reach the landed endpoints → the capture views and
  `raw.captures` are dbt sources; they map to one asset, `raw_in_warehouse` (design.md).
- Reproducing the CLI's retry, settle and skip logic in Dagster → the CLI owns it; Dagster calls
  the command and reads its exit code.

## Requirements

### R1. One description, run from the CLI and dbt

- R1.1 THE SYSTEM SHALL define the daily pipeline once, as Dagster assets in
  `orchestration/`, whose hand-written assets call the `front-office` CLI as a subprocess (the
  boundary `cli.py` states). The orchestration imports two modules of `front_office` and no others:
  `front_office.landing` (`LandingZone`, to read a settings capture, R3.3) and
  `front_office.privacy` (the patterns of R2.4).
- R1.2 THE SYSTEM SHALL define the assets: `mlb_captures` (`backfill mlb`), `espn_captures`
  (`backfill espn`), `espn_matchup_days` (`backfill espn --only matchup-days`), `idmap_capture`
  (`backfill idmap`), `raw_in_warehouse` (`upload` or `load`, R3.2), the dbt models through
  `dagster-dbt`, and `source_freshness` (`dbt source freshness`, in `daily` only when `FO_WAREHOUSE=duckdb`, R3.5)
  (ADR 0127).
- R1.3 THE SYSTEM SHALL read the real dbt manifest, unfiltered, with `dagster-dbt` pinned at 0.29.30
  or newer, one asset per model (ADR 0128).
- R1.4 THE SYSTEM SHALL run the steps one at a time, because two writers of the landing zone make
  the second fail with `LandingLocked`.

### R2. A failed step

- R2.1 WHEN a fetch command exits non-zero THE SYSTEM SHALL still materialize its asset and fail
  its non-blocking asset check `fetch_complete`, carrying the command's last error lines as
  metadata, so that upload and build still run (ADR 0129).
- R2.2 IF `upload` or the `dbt build` exits non-zero THEN THE SYSTEM SHALL fail that asset and skip
  what depends on it.
- R2.3 THE SYSTEM SHALL end a run in which any `fetch_complete` failed in a state a person can see
  as failed or warned in the UI and read by `dagster` GraphQL, which is what #219 reads.
- R2.4 THE SYSTEM SHALL write no ESPN credential, cookie, member name or account id to a Dagster
  log, event or metadata (AGENTS.md rules 2 and 3): the orchestration reads no credential file.
  What it records of a command is its arguments, its exit code and only the output lines that
  match an allowlist of the CLI's own line shapes (`landed …`, `boxscores: …`, `rosters: …`,
  `failed …`, `unproven …`, `scoring periods: …` and the like), after the patterns of
  `front_office/privacy.py` have dropped any that match them. Every other line is replaced by
  `<line withheld>`. No raw output is stored.

### R3. Season and warehouse

- R3.1 THE SYSTEM SHALL fetch the current calendar year in America/New_York as the season, unless
  `FO_SEASON` names another (ADR 0130).
- R3.2 THE SYSTEM SHALL choose the warehouse by `FO_WAREHOUSE`: `bigquery` runs
  `upload --project "$FO_BQ_PROJECT"` and builds with `--target bq --selector bigquery`;
  `duckdb` (the default) runs `load` and builds the `dev` target (ADR 0131). A run with
  `bigquery` and no `FO_BQ_PROJECT` fails before fetching.
- R3.3 WHEN the newest landed settings capture of the season has `latestScoringPeriod` greater than
  `finalScoringPeriod` THE SYSTEM SHALL run `espn_matchup_days`, and otherwise SHALL skip it
  without a request.
- R3.4 THE SYSTEM SHALL build with the unit tests excluded (`--exclude-resource-type unit_test`):
  CI holds them, and #221 decides whether BigQuery does.

- R3.5 WHILE `FO_WAREHOUSE=bigquery` THE SYSTEM SHALL leave `source_freshness` out of `daily`:
  the freshness filters in `_raw_feeds__sources.yml` are DuckDB SQL and are rewritten by hand for
  BigQuery (AGENTS.md; ADR 0050), and none is. A BigQuery freshness check is a follow-up issue that
  #219's stale-feed alert needs.
- R3.6 THE SYSTEM SHALL resolve the landing root once, from `FO_LANDING_ROOT` (an absolute path,
  default `data/raw` in the repository), and give that one path to every CLI command as `--raw-root`,
  to `season.is_over`, and to dbt as `FO_LANDING_ROOT` (`FO_CI_LANDING_ROOT` for the `ci` target),
  which `fo_landing_root()` reads.

### R4. Running it

- R4.1 THE SYSTEM SHALL give a job, `daily`, that selects the whole pipeline except `idmap_capture`
  and is what #218 schedules; `dagster job execute -m front_office_pipeline -j daily` runs it once without the
  daemon, from the repository root. The module is importable there because the wheel's packages
  include `orchestration/front_office_pipeline` (task 1).
- R4.2 THE SYSTEM SHALL leave `idmap_capture` outside `daily`: it is materialized by hand until
  #218 gives it a cadence (design.md, Open questions).
- R4.3 THE SYSTEM SHALL measure, with these definitions, the peak PSS of the daemon and the UI idle
  and of a `daily` run beside them, on arm64 on `mothership` or on a machine with the same limit
  (0216 R6.3), and record it on #217. IF that peak is over 2 GB (the limit proposed for the run's
  containers; 0216 measured 1.18 GB on a filtered manifest) THEN THE SYSTEM SHALL go back to the
  owner before #218.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| dbt assets loaded from the real manifest | 80: 73 non-ephemeral models and 7 seeds of the 2026-11-14 manifest (C1, C2) | `len(defs.get_asset_graph().get_all_asset_keys())` minus the 6 hand-written ones, recorded in task 5 |
| Hand-written assets | 6: `mlb_captures`, `espn_captures`, `espn_matchup_days`, `idmap_capture`, `raw_in_warehouse`, `source_freshness` | same listing |
| One local `daily` run on the real season, `FO_WAREHOUSE=duckdb` | every step succeeds; the dbt step passes as many nodes as `cd dbt && dbt build --exclude-resource-type unit_test` run directly just after (task 5 records both numbers) | the run's event log, recorded on #217 |
| A `daily` run with the ESPN command failing (cookies blanked in a copy) | `espn_captures` materialized, `fetch_complete` failed, upload and build still ran, run not reported green | task 6 |
| Season on 2027-01-01 05:00 ET | 2027 (and 2026 on 2026-12-31 23:00 ET) | unit test on `season.py` |
| `espn_matchup_days` gate on 2026's newest settings (188 > 180) / 2025's (196 > 188) | runs for both; a settings capture with latest 120, final 180 skips | unit test, and C3 |
| Memory | daemon + UI + a run under the VM's limit with 2 GB spare | task 7 |
