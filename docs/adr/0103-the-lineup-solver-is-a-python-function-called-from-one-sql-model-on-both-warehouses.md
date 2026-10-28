# 0103. The lineup solver is a Python function called from one SQL model on both warehouses

- Status: accepted; amends [0039](0039-the-optimal-lineup-is-solved-in-a-dbt-python-model-with-scipy.md)
- Date: 2026-10-26
- Spec: [0137-lineup-solver-on-bigquery](../specs/0137-lineup-solver-on-bigquery/design.md) · Issue: #137

## Context

ADR 0039 made the optimal lineup a dbt Python model that calls SciPy, and said it would
stay DuckDB-only or the solver would move: sub-project 3 decides. ADR 0096 left it, and
the three models that read it, out of what BigQuery builds.

dbt-bigquery runs a Python model only by sending it to Dataproc or to a Colab notebook
through BigQuery DataFrames. Both need a Cloud Storage bucket, and services the project
has not enabled. Neither can import a local module (spec 0137, C1, C2). BigQuery also runs
Python **UDFs**: functions called from SQL, executed in a container with PyPI packages
(C3). A probe ran today's solver unchanged as one, over the real season. It returned
162,974 rows, as DuckDB does, and exactly the rows the local solver gives on the same
inputs (C6, C7). On DuckDB, the same function registered on the connection and called
from SQL gives the Python model's rows exactly, in 9 s instead of 56 s (C14). dbt 1.11
creates UDFs as **function resources**, on BigQuery but not DuckDB, and a dbt-duckdb
plugin can register a Python function on each connection (C15 to C17).

## Decision drivers

- BigQuery builds the whole project in `dbt build`, with nothing to run or own outside it.
- One copy of the solver, tested once.
- The same rows on both warehouses (with ADR 0104).
- No new GCP infrastructure for a portfolio project with a 5 USD monthly budget.

## Considered options

1. **A Python UDF, called from one SQL model on both warehouses.** The function file is the
   UDF body on BigQuery and is registered by a dbt-duckdb plugin on DuckDB.
2. **A UDF on BigQuery, and the Python model kept on DuckDB.** Two models compute one table.
3. **A dbt Python model through BigQuery DataFrames** (a Colab notebook job).
4. **A dbt Python model through Dataproc Serverless** (a Spark batch).
5. **Solve outside dbt**, writing a table dbt reads as a source.
6. **Rewrite the solver** in JavaScript or SQL.

## Decision

Chosen by the owner on 2026-10-26, going through the spec's decisions, as recommended:
**option 1**. The owner weighed its cost (C20) against option 5, the only one free on
BigQuery.

`int_fantasy__optimal_lineups` becomes a SQL model, materialized as a table. It calls
`solve_lineup_period` once per team-period, with an array of option structs. The function
is `dbt/functions/solve_lineup_period.py`: today's `lineup_solver.py` plus an entry point.
On BigQuery it is a dbt function resource, Python 3.11, with `scipy==1.17.1` and
`numpy==1.26.4`. On DuckDB the resource is disabled, and a plugin registers the same file.

Option 2 writes every rule twice. Options 3 and 4 need a bucket, new APIs and a runtime
started per build, and were not measured. Option 5 takes the result out of the DAG, which
ADR 0039 rejected. Option 6 means owning an exact solver, which ADR 0039 chose not to.

## Consequences

- Good: no service, bucket or runtime to own. The solve runs inside BigQuery's query.
- Good: one file is the BigQuery body, the DuckDB function and the tested module.
- Good: the model is SQL, so the dbt unit-test framework can test it on DuckDB (expected;
  spec 0137, open question 1). The Python model could not be unit-tested.
- Good: the DuckDB build's solver node drops from 56 s to about 9 s (C14, #201).
- Bad / accepted cost: BigQuery runs Python 3.11 and pins `numpy<2` (C3, C5), so the UDF
  runs older SciPy and NumPy than the dev environment. Its output is held by comparing
  rows, not versions (C7).
- Bad / accepted cost: the signature is declared twice, in BigQuery's YAML and in the
  plugin's DuckDB types. A test holds them together.
- Bad / accepted cost: the function exists only on dbt's DuckDB connections, so the model
  must be a table: a view calling it fails when read outside dbt (C16).
- Bad / accepted cost: not free. Python UDFs (GA since 2026-06-22) are billed as BigQuery
  Services, 0.06 USD a slot-hour with no free tier. The probe's execution was about
  0.0004 USD for the eight seasons. Image builds are billed on top, at an amount not yet
  seen (C20). Only an option that keeps Python out of BigQuery (5) costs nothing there.
- Bad / accepted cost: ADR 0039's "a dbt Python model" no longer holds. Its choice of SciPy
  and the solver's rules do. ADR 0039 is amended by this record.
- Follow-ups: if BigQuery rebuilds the UDF image on every build, build the function only
  when it changes.
