# Spike: a representative slice of the dbt project on BigQuery — requirements

Issue: #130 · Tier: L · Status: draft

## Problem

The README says of the BigQuery migration that "portability is not yet verified", and
every design since sub-project 1 has assumed the migration only touches the `fo_json_*`
macros. Measured on 2026-10-11, that assumption is false. BigQuery's own parser was asked
(by dry run, nothing executed) about 47 constructs the project uses, and refused 21. Most
of the 21 are written in models, not in macros:

| Construct | Where it is written today | BigQuery |
|---|---|---|
| `count(*) filter (where …)` | 69 times in 16 files | syntax error |
| `sum(x order by k)`, `avg`, `corr` (the rule of ADR 0046) | 11 model files | refused |
| `unnest(list) as x` in a SELECT list | 32 times in 18 files | syntax error |
| `x::type` | 24 times in 9 files | refused |
| `try_cast`, `strptime`, `generate_series`, `range`, `list(…)`, `to_timestamp(n)`, `bool_or`, `epoch_ms`, `map_values` | models and macros | function not found |
| a JSON path with a wildcard: `$.schedule[*]`, `$.dates[*].games[*]` | arguments of `fo_json_array`, in 10 files | passes a dry run, fails when run |
| types `varchar`, `double`, `timestamptz` | 6, 16 and 1 files | type not found |
| `at time zone` | `fo_eastern_date` | syntax error |
| `->>`, `from_json` | `dbt/macros/json.sql` only | refused |
| `insert` (any DML) | nowhere in dbt; `load.py` | refused: the project was in the sandbox when asked. The owner chose on 2026-10-11 to link a billing account first, which lifts this |

Three behaviours differ as well, seen by running constant-only queries (0 bytes billed):
BigQuery's JSON type returns an object's keys sorted, not in document order; it has no
wildcard path (`$.players.*`), which `fo_json_values` and so every boxscore model rest on;
and `json_keys` is recursive unless told a depth. And a float `sum` in BigQuery depends on
row order just as DuckDB's does (0.6 one way, 0.6000000000000001 the other), with no way
to state the order.

This list is what has been found, not what there is. It grew by four during this spec's
own design review, and one of its entries shows that a dry run does not catch everything.
Only building the models on BigQuery finds the rest.

So the cost of the migration is unknown, and the milestone's issues cannot be written
honestly until one real slice has been taken all the way through.

## Goals

- One slice of the project builds on BigQuery from the real season's captures, with its
  tests, and its numbers are compared with the DuckDB build of the same slice.
- DuckDB is unchanged by it: the real warehouse built from the ported models equals the
  one built before, exactly.
- The way a model is written for two warehouses is settled by having been used on 30
  models, not argued.
- What the migration costs is known: bytes scanned per build, every model that had to
  change and how, and what could not be made the same.
- The remaining issues of the milestone are filed from that evidence.

## No-gos

Explicitly out of scope. Work that drifts here is escalated, not done.

- The 27 models outside the slice, and the seed `espn_activity_types` only they read.
- The lineup solver's Python model (ADR 0039). The slice does not contain it. Where it
  runs on BigQuery is its own issue, filed at the end of this one.
- Uploading captures of ESPN `teams` or `transactions`, the two endpoints that carry
  league members' data (see *Expected values*), or of MLB `players`.
- A production loader: Cloud Storage, an incremental or append-only load, the key
  collision check of ADR 0011 on BigQuery. The spike reloads its table whole.
- BigQuery in CI or in `.agentic/gates`. Both stay DuckDB-only and unchanged.
- Any billed service other than BigQuery jobs and the one bucket of R6.6. The owner
  chose on 2026-10-11 to link a billing account before the spike runs; the spike still
  loads by a load job and builds nothing on what billing newly allows.
- Linting the BigQuery SQL with sqlfluff.
- Rewriting the freshness filters of `_raw_feeds__sources.yml` (ADR 0050). Nothing runs
  `dbt source freshness`.
- Any change to what a model computes. A ported model returns the rows it returned.
  *Amended 2026-10-11:* with one exception the owner accepted, the tie-break of
  `stg_mlb__games` (R4.4).

## Rabbit holes

- Making floats bit-identical across two engines → not attempted. Float columns are held
  to a tolerance and the largest difference is reported (R5, ADR 0053). Whether the
  project wants exact decimals instead is a question the evidence informs, later.
- dbt's own cross-database macros (`dbt.safe_cast`, `dbt.type_float`, …) → used only where
  the SQL they emit for DuckDB is the SQL the model has today. `dbt.type_float()` is
  `float` by default, which in DuckDB is 32-bit: it would change numbers silently. Types
  go through `fo_type_*` (design).
- Porting a model "while we are in there" → the slice is fixed by a selector (R1.1). A
  model outside it is not edited, even where the change is the same one line.
- Unit tests that do not run on BigQuery for a reason of dbt's (fixture typing of a JSON
  column, for one) → recorded as a finding with the error, not worked around by changing
  what the test checks.
- The 24 GB lesson of rule 1 → the BigQuery forms keep the same shape (payload projected
  away before any unnest). Whether BigQuery needs it is not investigated.
- A query that scans far more than expected → every BigQuery query is capped (R2.4); a
  refused query is a finding, and the cap is not raised without the owner.

## Requirements

### R1. The slice

What is ported, fixed in one place.

- R1.1 THE SYSTEM SHALL define a dbt selector `bigquery_slice` that selects
  `fct_matchup_results`, `rec_espn__category_result_differences` and
  `int_fantasy__category_scales`, each with everything upstream of it.
- R1.2 THE SYSTEM SHALL have that selector select exactly 30 models and 6 seeds, and no
  Python model.
- R1.3 THE SYSTEM SHALL build BigQuery only through that selector: no command of the
  spike builds an unselected model there.
- R1.4 THE SYSTEM SHALL have that selector take a test only when every model the test
  reads is selected (`indirect_selection: cautious`), so that no selected test reads a
  relation BigQuery does not have.

### R2. A BigQuery target

- R2.1 THE SYSTEM SHALL provide a dbt target `bq` in `dbt/profiles.yml` that authenticates
  with application-default credentials (`method: oauth`), reads its project id from the
  environment variable `FO_BQ_PROJECT`, and names the location `US`.
- R2.2 THE SYSTEM SHALL keep `dev` the default target, and `dev` and `ci` as they are.
- R2.3 THE SYSTEM SHALL keep `dbt-bigquery` out of the dependencies CI installs: it is in
  a dependency group of its own that `uv sync --locked` does not install by default.
- R2.4 THE SYSTEM SHALL cap every query of the `bq` target at 10 GB billed
  (`maximum_bytes_billed`), so that a query over the cap fails instead of running.
- R2.5 IF `FO_BQ_PROJECT` is not set THEN THE SYSTEM SHALL fail the `bq` target with a
  message naming the variable, and `dev` and `ci` SHALL be unaffected.
- R2.6 THE SYSTEM SHALL keep every credential outside the repository: no key file and no
  token is committed, and no file of the repository names a service account. The project
  id is configuration, not a secret, and is still read from the environment and not
  written into `profiles.yml`.

- R2.7 THE SYSTEM SHALL run no BigQuery job until the owner has linked a billing
  account to the project and created a Cloud Billing budget for it with an alert, at an
  amount the owner sets, and has said so on #130. Both are the owner's to do. The build
  SHALL confirm that billing is enabled on the project before its first job, and SHALL
  NOT create, change or remove a billing account or a budget.

### R3. The raw rows on BigQuery

- R3.1 WHEN the spike's loader runs THE SYSTEM SHALL write `raw.api_responses` on
  BigQuery by a load job, replacing the table, with the columns of the DuckDB table,
  `payload` and `partitions` typed `JSON`, clustered by `source` and `endpoint`.
- R3.2 THE SYSTEM SHALL take the rows from the local warehouse's `raw.api_responses`, and
  only those of an allowlist of seven endpoints: `mlb/boxscore`, `mlb/schedule`,
  `espn/roster`, `espn/matchups`, `espn/settings`, `espn/pro_schedule`,
  `idmap/player_id_map`.
- R3.3 IF a row to be uploaded holds a key of `privacy.FORBIDDEN_KEYS`, other than
  `firstName` or `lastName` directly in a `playerPoolEntry.player` object (a ballplayer's
  own name), or IF a row of source `espn` holds a GUID, THEN THE SYSTEM SHALL upload
  nothing and name the endpoint and the path, never the value. MLB rows are not checked
  for GUIDs: `gameGuid` is a public game id.
- R3.4 WHEN the load has finished THE SYSTEM SHALL read every loaded row back, pair it
  with its source row by the five key columns, and fail unless each pair's `file_path` is
  the same text, its `payload` and `partitions` are equal as parsed JSON, and each side
  has no row the other lacks. Parsed, because the two warehouses write the same JSON as
  different text.
- R3.5 THE SYSTEM SHALL write its intermediate files under `data/`, which is gitignored,
  and nowhere else.

### R4. One model, two warehouses

- R4.1 THE SYSTEM SHALL have each model, macro and singular test of the slice exist once,
  and compile for both `dev` and `bq`.
- R4.2 THE SYSTEM SHALL write what both warehouses accept as plain SQL, and reach
  everything else through a dispatched `fo_*` macro with a DuckDB form and a BigQuery
  form (ADR 0051). A model file of the slice SHALL contain none of the constructs
  BigQuery refused.
- R4.3 A test in `ingestion/tests/` SHALL fail when a model or singular test of the
  slice, or a macro one of them calls, directly or through another macro, contains one of
  the known refused constructs outside a `duckdb__` form, as `test_dbt_json_rule.py` does
  for JSON.
- R4.7 WHEN the slice is built on `bq` with dbt's `--empty` flag (every input limited to
  no rows, so the SQL of every model and data test is run and nothing is scanned) THE
  SYSTEM SHALL complete without an error from BigQuery. This, not the list, is what shows
  no refused construct is left; each one it finds is added to the list and to R4.3's test.
- R4.4 WHEN the real season is built on `dev` from the ported models THE SYSTEM SHALL
  produce a warehouse equal to the one built from `main` at the spike's base commit:
  `scripts/compare_warehouses.py OLD NEW --strict-columns` exits 0, over every relation
  and not only the slice's.
  *Amended 2026-10-11 by the owner's decision (design.md, Amendments):* comparing the two
  warehouses showed that `stg_mlb__games` kept one of two tied schedule entries with no
  rule, and each warehouse kept a different one. The tie-break the owner chose changes 26
  rows of that model on DuckDB, in no `official_date` or `is_played`, and no other
  relation. So the requirement is held in two parts: the warehouse built from the port
  before the tie-break equals the base commit's, 56 of 56 relations; the warehouse built
  after it differs from the base commit's in those 26 rows only, and is the baseline
  (`data/warehouse_baseline2.duckdb`) that every later build equals, 56 of 56.
- R4.5 THE SYSTEM SHALL leave the DuckDB type of every column of every relation as it
  was.
- R4.6 `.agentic/gates` SHALL pass, unchanged except for the new test of R4.3.

### R5. The same numbers

- R5.1 WHEN the slice is built on `bq` from the rows of R3 THE SYSTEM SHALL build its 29
  relations and 6 seeds, and every data test wholly inside the slice SHALL pass, with the
  same variables as the `dev` build (`anonymize: false`).
- R5.2 WHEN the two builds are compared THE SYSTEM SHALL find, for each of the 29
  relations, the same row count, and the same rows over every column that is not
  floating-point (compared as multisets, both ways).
- R5.3 WHEN the two builds are compared THE SYSTEM SHALL join each relation that has
  floating-point columns on its declared unique key and find every pair of values equal
  within a relative difference of 1e-9, or an absolute difference of 1e-12 where both are
  below 1e-3 in magnitude (ADR 0053); a null on one side only is a difference.
- R5.4 THE SYSTEM SHALL report, per floating-point column, how many values are exactly
  equal and the largest difference found.
- R5.5 WHEN the slice is built on `bq` a second time from the same rows THE SYSTEM SHALL
  report whether the two BigQuery builds are exactly equal, floats included. This is
  reported and not required to hold.
- R5.6 WHEN the unit tests of the slice's models are run on `bq` THE SYSTEM SHALL report
  each as passed, failed, or not runnable with dbt's error. A failed one is a difference
  to explain before the spike is done; a not-runnable one is a finding.

### R6. What it cost

- R6.1 THE SYSTEM SHALL report bytes billed per model and in total for one `bq` build of
  the slice, read from dbt's `run_results.json`, and the same for its tests.
- R6.2 THE SYSTEM SHALL report every file changed, grouped by the construct that forced
  the change, with the count of each across the 27 models not ported.
- R6.3 THE SYSTEM SHALL report whether anything in the build needed DML or was otherwise
  refused.
- R6.4 THE SYSTEM SHALL report, for one boxscore model, bytes billed with `payload` as
  `JSON` and as `STRING`.
- R6.6 THE SYSTEM SHALL measure, once, the likely production shape (ADR 0052, option
  3): the `mlb/boxscore` rows written to a private Cloud Storage bucket in `US` and read
  through an external table, with one boxscore model built against it; and SHALL report
  its bytes billed and time beside the native table's. Only `mlb/boxscore` goes to the
  bucket: it is on the allowlist of R3.2 and is public MLB data. The bucket has uniform
  access and no public access, and is deleted, with the external table, when the figures
  are recorded. The slice is not built on it.
- R6.5 THE SYSTEM SHALL post R5.2 to R6.4 and R6.6 as one comment on #130, and file the remaining
  issues of the milestone, each citing the finding it comes from.

## Expected values

How correctness is checked against real data, not just fixtures. Counts are of the real
warehouse as built on 2026-10-10; the binding rule is equality with a `dev` build of the
same commit from the same raw rows (R5.2, R5.3), and these are what that build is expected
to show.

| Check | Expected | How to verify |
|---|---|---|
| Models and seeds in the slice | 30 models (21 tables, 8 views, 1 ephemeral), 6 seeds, no Python model | `dbt ls --selector bigquery_slice` |
| Tests in the slice | 204 data tests wholly inside it (179 generic, 25 singular); 59 unit tests, 61 with the two tie-break tests (amended 2026-10-11) | `dbt ls --selector bigquery_slice --resource-type test` / `unit_test` |
| Raw rows uploaded | 5,179 of 5,192: boxscore 4,950, roster 182, settings 13, schedule 12, matchups 12, pro_schedule 9, player_id_map 1; each equal to its source as parsed JSON | R3.4 |
| Raw rows not uploaded | 13: transactions 7, teams 5, players 1 | the same query on `dev` |
| Member data in the seven endpoints | 0 account GUIDs; `firstName`/`lastName` only under `playerPoolEntry.player` | R3.3 passes |
| Rows in the 29 relations | 444,634 in all | sum of R5.2's counts |
| `fct_matchup_category_scores` | 4,862 rows, one season (2026) | R5.2 |
| `fct_matchup_results` | 143 rows | R5.2 |
| `stg_espn__roster_entries`, `int_fantasy__roster_days` | 55,653 rows each | R5.2 |
| `stg_mlb__batting_game_logs` / `stg_mlb__pitching_game_logs` | 51,708 / 20,800 rows | R5.2 |
| `int_mlb__player_game_days` | 71,880 rows | R5.2 |
| `rec_espn__matchup_stat_differences` by status | match 6,816 · bye 48 · registered 31 · explained_by_component 17 | `group by status` on both |
| `rec_espn__category_result_differences` by status | match 4,856 · explained 6 | `group by status` on both |
| `int_fantasy__category_scales` | 17 rows, all `prior_and_current_seasons` | R5.2; its 3 float columns under R5.3 |
| Relations with floating-point columns | 7, each with a declared unique key | R5.3 covers all 7 |
| `dev` after the port | equal to `dev` before, every relation; after the game tie-break (amended 2026-10-11), 55 of 56 relations, `stg_mlb__games` differing in 26 rows, and equal to the retaken baseline | R4.4, in its two parts |
| Any one `bq` query | at most 10 GB billed | R2.4; the build does not fail on the cap |
