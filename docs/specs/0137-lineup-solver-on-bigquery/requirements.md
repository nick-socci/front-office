# The lineup solver on BigQuery — requirements

Issue: #137 · Tier: L · Status: draft

## Problem

`int_fantasy__optimal_lineups` is a dbt Python model that calls SciPy (ADR 0039). dbt-duckdb
runs it in the dbt process. dbt-bigquery can run a Python model only by sending it to
Dataproc or to a Colab notebook through BigQuery DataFrames, and both need a Cloud Storage
bucket and services this project has not turned on (design C1, C2). So BigQuery builds
every model but this one and the three that read it (ADR 0096). Those three are ported and
run there over no rows, but never from real rows (#137, comment of 2026-10-24).

Grounding this spec found two things:

- BigQuery runs the solver unchanged as a **Python user-defined function** (UDF): one
  function call per team-period, made from SQL. A probe on the real season returned
  162,974 rows, as DuckDB does (C6). Solving BigQuery's inputs locally gives exactly the
  UDF's rows (C7).
- BigQuery's rows still differ from DuckDB's in 1,896 rows over 1,187 team-days (C9).
  BigQuery's option values differ from DuckDB's in the last digits (largest relative
  difference 1.05e-11, C8; the effect ADR 0053 accepts and #139 tracks). In every one of
  those team-days the two lineups have equal value to within 4.4e-16. That noise picks
  between exact ties, and 94 of the team-days field other players.

## Goals

- BigQuery builds the whole project, the lineup solver and its three readers included,
  inside `dbt build`, with no Spark, notebook runtime, bucket or service beyond BigQuery.
- The solver exists once: one Python file is what BigQuery runs, what DuckDB runs and what
  pytest tests.
- On the real season, BigQuery's optimal lineups equal DuckDB's row for row, and the readers
  meet ADR 0053: everything that is not a float exactly, floats within tolerance.
- The DuckDB build changes only where an exact tie is now broken the same way on both
  warehouses, and the change is counted and bounded before it lands.

## No-gos

- Changing what a lineup option is worth, or the solver's rules: the cap, the tie bonus,
  ADR 0037's rule, the period problem (ADRs 0090, 0091). Only how the solver is called, and
  the rounding of its input in R3, change.
- Making BigQuery's float aggregates agree with DuckDB's (#139). The rounding in R3 makes
  the solver insensitive to that noise. It does not remove the noise.
- Dataproc, BigQuery DataFrames, Colab runtimes, Cloud Storage buckets, Cloud Run, remote
  functions. None is set up.
- BigQuery in CI or in `.agentic/gates`. CI stays on DuckDB fixtures. BigQuery is verified
  by hand on the real season, as in specs 0130 and 0135.
- Running dbt unit tests on BigQuery (#138). BigQuery builds keep
  `--exclude-resource-type unit_test`.
- Making the solve faster (#201) beyond what moving it gives. What it gives is recorded on
  #201, and that issue is not closed here.
- Orchestration (sub-project 4) and the production loader (#140).

## Rabbit holes

- **A JSON or nested value crossing into the UDF.** BigQuery Python UDFs refuse `JSON`
  arguments (C3). → The options go in as an `ARRAY` of `STRUCT`s of plain types, which the
  probe passed (C6).
- **Package versions.** BigQuery runs Python 3.11 only, and its environment pins
  `numpy<2` (C3, C5). The newest SciPy for that is 1.17.1, and locally the project uses
  1.18.1 on 3.13 (C4). → Pin the UDF's versions, don't try to match local ones. R2.3 holds
  the result by comparing rows, which C7 shows equal.
- **The ties themselves.** Breaking ties by a stated order inside the solver (a second,
  smaller bonus by player id) would interact with the 1e-9 tie bonus of spec 0012. →
  Round the input instead (ADR 0104), and measure what it changes (C10, C11).
- **dbt function resources on DuckDB.** dbt-duckdb has no function materialization (C17).
  → Disable the function resource on DuckDB and register the same Python function through
  a dbt-duckdb plugin (C15, C16).
- **The UDF's cost.** A Python UDF is billed as BigQuery Services: 0.06 USD a slot-hour,
  with no free tier (C20). Execution was about 0.0004 USD on the probe, and image builds
  are billed on top. → Measure both on the real build (R5.4). The project's 5 USD monthly
  budget alerts at 50%.

## Requirements

### R1. One solver, called from one SQL model on both warehouses

- R1.1 THE SYSTEM SHALL build `int_fantasy__optimal_lineups` as a SQL model, materialized
  as a table, that passes each team-period's options to one function,
  `solve_lineup_period`, on DuckDB and on BigQuery.
- R1.2 THE SYSTEM SHALL hold the solver and the function's entry point in one Python file,
  `dbt/functions/solve_lineup_period.py`. That file is the body of the BigQuery UDF (a
  dbt function resource), the module the DuckDB plugin registers, and what pytest
  imports. No other copy of the solver exists.
- R1.3 WHEN dbt builds on BigQuery THE SYSTEM SHALL create or replace the function before
  the model that calls it, as a node of the DAG.
- R1.4 WHEN dbt builds on DuckDB THE SYSTEM SHALL register the function on each
  connection through a dbt-duckdb plugin, and the function resource SHALL be disabled
  there.
- R1.5 THE SYSTEM SHALL remove the Python model `int_fantasy__optimal_lineups.py` and
  `dbt/python_modules/lineup_solver.py`.

### R2. The rules of specs 0012 and 0164 are kept

- R2.1 THE SYSTEM SHALL return one row per team-day and assigned player, with the same
  seven columns and types as today.
- R2.2 IF any option of a team-period has a null value THEN THE SYSTEM SHALL return no rows
  for that team-period. Every non-null value is still checked against the bound first
  (spec 0164, R1.8).
- R2.3 IF an option's value is beyond the solver's bound THEN THE SYSTEM SHALL fail the
  build with a message naming the team-day, on both warehouses.
- R2.4 IF a team-day's date is in no matchup period THEN THE SYSTEM SHALL fail the build
  with a message naming the team-day, on both warehouses.
- R2.5 THE SYSTEM SHALL keep the start cap of spec 0164: the floor of the period's limit,
  or the actual lineup's starts where it went past it. A league-season with no limit is
  solved a day at a time.

### R3. Ties are broken the same way on both warehouses (ADR 0104)

- R3.1 THE SYSTEM SHALL round each option's value to 12 decimal places, inside the
  function, before solving. The rounding is Python's `round`, so both warehouses round the
  same double the same way.
- R3.2 WHEN the real season is built on both warehouses THE SYSTEM SHALL give identical
  `int_fantasy__optimal_lineups` rows: `EXCEPT ALL` empty both ways. Any difference fails
  acceptance, whatever its explanation.
- R3.3 IF the two warehouses' rows differ THEN the comparison SHALL print each team-day
  that differs, with its rows on each side, so the owner can decide (ADR 0104).

### R4. The DuckDB warehouse

- R4.1 WHEN the real season is rebuilt THE SYSTEM SHALL leave every relation equal to
  `main`'s build, except `int_fantasy__optimal_lineups` and the three models that read it.
- R4.2 THE SYSTEM SHALL change `int_fantasy__optimal_lineups` only in team-days whose new
  and old lineups have the same number of players, the same number of kept actual
  players, and values equal within 1e-12. In each changed team-period, the credited value
  under the start rule SHALL be equal within 1e-12. Both are judged with `main`'s option
  values, by `probes/compare_solves.py`. The expected counts are in *Expected values*.
- R4.3 THE SYSTEM SHALL change the three readers only in the team-periods of R4.2's
  team-days. The counts are recorded on #137.

### R5. The BigQuery build

- R5.1 THE SYSTEM SHALL drop the exclusion of the solver and its readers from the BigQuery
  selector (ADR 0096). That selector is renamed `bigquery` (ADR 0105).
- R5.2 THE SYSTEM SHALL declare the UDF with `runtime_version` 3.11 and pinned packages:
  `scipy==1.17.1` and `numpy==1.26.4`.
- R5.3 WHEN the real season is built on BigQuery THE SYSTEM SHALL pass every model and data
  test of the selector, and `scripts/compare_bigquery.py` SHALL pass every relation,
  the solver and its readers included.
- R5.4 WHEN the real build is run THE SYSTEM SHALL record on #137, for a first and a
  second consecutive build: the function's and the model's wall time, bytes billed, slot
  time and `externalServiceCosts` (the UDF's own billed slot-ms). The owner adds the cost
  billed for the Python UDF SKUs that day.
- R5.5 WHEN the selector is run with `--empty` and a `fo_schema_suffix` THE SYSTEM SHALL
  build the function and all models with no refusal.

### R6. Tests

- R6.1 THE SYSTEM SHALL keep every pytest of the solver passing against the moved file.
- R6.2 THE SYSTEM SHALL hold each behaviour now tested through the Python model (the ten
  tests of `test_optimal_lineups_model.py`) with a test of the SQL model on DuckDB, a dbt
  unit test where one can run, else a pytest.
- R6.3 THE SYSTEM SHALL fail a test if the function's argument or return types declared
  for BigQuery (YAML) and for DuckDB (the plugin) name different fields, in a different
  order, or of different kinds.
- R6.4 THE SYSTEM SHALL fail a test if any model other than this one calls
  `solve_lineup_period`, or if a view calls it. A view would fail when read outside dbt
  (C16).
- R6.5 THE SYSTEM SHALL keep `test_dbt_portable_sql_rule.py`, the plan-shape check and the
  rest of the gates passing, with the new model held to ADR 0051.

### R7. Records and docs

- R7.1 THE SYSTEM SHALL mark ADR 0039 `amended by` ADR 0103, and ADR 0096 `amended by`
  ADR 0105, once those are accepted.
- R7.2 THE SYSTEM SHALL update README, AGENTS.md, `profiles.yml` and the model's YAML
  description wherever they say the solver is a Python model or DuckDB-only, or name
  `bigquery_slice`.

## Expected values

Measured at `main` 1c81306 on the real season, eight league-seasons (design C9 to C14).

| Check | Expected | How to verify |
|---|---|---|
| `int_fantasy__optimal_lineups` rows, DuckDB | 162,974 (unchanged) | `count(*)` |
| Team-periods solved | 2,340 | distinct team-periods in the options |
| Team-days that change against `main` on DuckDB (R4.2) | 1,231 in 911 team-periods (1,987 rows each way), every one a tie: gap ≤ 1e-12, same size and kept count, same credited period value | `probes/compare_solves.py compare` |
| BigQuery rows against DuckDB rows (R3.2) | 0 and 0 | `EXCEPT ALL` both ways |
| Relations other than the solver and its readers, DuckDB against `main` | identical | `scripts/compare_warehouses.py` |
| Solver node time, DuckDB, eight seasons | about 9 s (56 s today) | `run_results.json` |
| BigQuery comparison | every relation passes | `scripts/compare_bigquery.py` |
