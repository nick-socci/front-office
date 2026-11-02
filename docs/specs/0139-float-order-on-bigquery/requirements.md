# A float aggregate is computed in its stated order on BigQuery too — requirements

Issue: #139 · Tier: L · Status: draft

## Problem

ADR 0046 makes every floating-point aggregate state its order, so that a build reproduces
itself to the last digit. BigQuery refuses `order by` inside `sum`, `avg` and `corr`, so
the BigQuery forms of the three `fo_*_in_order` macros drop it, and ADR 0053 holds a
BigQuery build to a tolerance on float columns. The result: two BigQuery builds of the
same rows differ from each other in 2 of 29 relations (#130, R5.5). Four unit tests fail
on BigQuery and only there (#138). And float noise has already changed a column that is
not a float: `fct_lineup_decisions` named a different missed start until its order was
rounded (#137). This has to be settled before BigQuery becomes the warehouse of record
(#140).

## Goals

- On BigQuery, each of the 35 ordered float aggregates is computed in the order it
  states, and gives the digits DuckDB gives.
- A BigQuery build equals the DuckDB build of the same rows exactly, floats included, and
  equals its own previous build exactly.
- The four unit tests of #139 pass on both warehouses, unchanged.
- DuckDB's SQL, and so its warehouse, does not change.

## No-gos

- No change to what any model computes, or to any DuckDB form. The DuckDB compile of
  every model and test is byte-for-byte what it was (R1.4), with one exception the owner
  approves call by call: a sum task 1 finds to be of whole numbers (R1.6).
- No tolerance, rounding or exemption added for a float column that turns out to differ.
  Such a column goes to the owner with its cause (ADR 0116).
- ADR 0104's rounding of the lineup order and the solver's inputs stays as it is. It
  breaks ties between equal values, which ordering a sum does not do.
- No change to the aggregates that are exact in any order: `min`, `max`, `count`, and the
  `order-exempt:` sums of whole numbers.
- No new check that each `order by` is unique within its group. ADR 0046 asks for it, and
  the inventory (task 1) reads each call for it, but a runtime check is another issue.
- CI does not connect to BigQuery (ADR 0110). The BigQuery runs are by hand and recorded
  on #139.
- The populated default BigQuery datasets are not rebuilt. The acceptance builds go into
  suffixed datasets.

## Rabbit holes

- Reimplementing DuckDB's algorithms in general → only the three it uses here: a
  left-to-right sum, the mean as that sum over the count, and `corr` as one Welford pass.
  Each is checked against DuckDB on real and random data (C2, C3, R3.3).
- Making floats exact by other means (decimals, fsum, rounding) → measured and rejected
  in ADR 0115. Not revisited during the build.
- A BigQuery JavaScript *aggregate* function (UDAF) → BigQuery merges partial states in
  no fixed order, so it cannot fold in order. A scalar function over an ordered array is
  the form that can.
- Chasing a float difference the acceptance build finds in a column outside the 35
  aggregates → trace it far enough to name its cause, then stop and take it to the owner
  (R4.3).

## Requirements

### R1. The order is stated on BigQuery

- R1.1 WHEN a model or test calls `fo_sum_in_order(x, k)` on BigQuery THE SYSTEM SHALL
  add the non-null values of `x` one at a time, in the order of `k`, starting from 0.0,
  and return null if there are none.
- R1.2 WHEN `fo_avg_in_order(x, k)` is called on BigQuery THE SYSTEM SHALL return R1.1's
  sum divided by the count of non-null values of `x`, and null if there are none.
- R1.3 WHEN `fo_corr_in_order(y, x, k)` is called on BigQuery THE SYSTEM SHALL fold the
  pairs where both are non-null, in the order of `k`, as DuckDB 1.5.5's `corr` does:
  Welford's update for the co-moment and for each variance, then the population
  covariance over the product of the population standard deviations. It SHALL return null
  over no pairs, and NaN where DuckDB does (a single pair, a zero variance).
- R1.4 THE SYSTEM SHALL compile every model and test on the DuckDB targets to the SQL it
  compiles to on `main` before this work, except a call changed under R1.6.
- R1.5 THE SYSTEM SHALL define the folds as dbt function resources in JavaScript, built on
  BigQuery and disabled on DuckDB, as `solve_lineup_period` is (ADR 0103), and declared
  deterministic. Models reach them only through the three macros.
- R1.6 IF a call's expression is not a float on BigQuery THEN the BigQuery `--empty` run
  SHALL fail on it. Such a call is a sum of whole numbers, which needs no order on either
  warehouse. With the owner's approval of task 1's list, it becomes a plain `sum` with an
  `order-exempt:` comment (ADR 0046), not a cast. Its DuckDB SQL then loses an order it
  never needed, and the DuckDB build of its model SHALL be identical to `main`'s
  (`compare_warehouses.py` on that model and its descendants).

### R2. The comparison is exact

- R2.1 WHEN `compare_bigquery.py` compares a BigQuery build with a DuckDB build THE SYSTEM
  SHALL compare every scalar column, floats included, as a multiset of rows both ways, as
  `--bq-against-bq` does now, and pass only if all are equal (ADR 0116). JSON and nested
  columns stay outside the comparison, as they are today (the docstring's item 6): both
  sides must have them, and the models that read them are compared.
- R2.2 THE SYSTEM SHALL remove the float tolerance, its unique-key join and its
  per-column difference report from `compare_bigquery.py`, and keep everything else it
  does: kinds, JSON and nested columns, views, GROUPS.
- R2.3 WHEN a relation differs THE SYSTEM SHALL print its counts each way and, for each
  float column, whether the rows still differ with that column and every non-float
  column compared (and the other float columns left out). So a float difference is named
  by its column even when values only moved between rows.

### R3. Tests

- R3.1 WHEN the unit tests run on either warehouse THE SYSTEM SHALL pass all of them,
  the four of #139 included, with their `expect` blocks unchanged.
- R3.2 THE SYSTEM SHALL have unit tests, run on both warehouses, for the edges of R1.1 to
  R1.3: a group whose values are all null; a null among values, left out of the sum and
  the count; a single pair and a zero variance for `corr` (NaN); a group of one value.
- R3.3 WHEN pytest runs THE SYSTEM SHALL compare DuckDB's ordered `sum`, `avg` and `corr`
  with a Python fold written to mirror the JavaScript, exactly, on seeded random inputs
  (group sizes from 1 to 500, nulls, mixed magnitudes and signs). It fails if a DuckDB
  upgrade changes the algorithm.
- R3.4 THE SYSTEM SHALL hold each JavaScript file to what its quoting needs: no `'''` and
  no Jinja delimiter, as the solver's file is held.

### R4. Verified on the real season

- R4.1 WHEN the branch is built on BigQuery into suffixed datasets from the same captures
  as the real DuckDB warehouse THE SYSTEM SHALL pass `compare_bigquery.py` (R2.1) on every
  relation.
- R4.2 WHEN the 13 models with ordered aggregates, and every node downstream of them, are
  built a second time into the same suffixed datasets THE SYSTEM SHALL give tables
  exactly equal to the first build's (`--bq-against-bq`, or a comparison of copies taken
  before the rebuild).
- R4.3 IF a float column differs in R4.1 or R4.2 THEN the build SHALL trace it to the
  expression that differs and take it to the owner, and SHALL NOT be reported
  merge-ready until the owner has decided.

### R5. The record says so

- R5.1 THE SYSTEM SHALL state the rule where the next author looks: the comment above the
  three macros in `portable.sql`, AGENTS.md (whose line on "the four float tests of #139"
  goes), and `compare_bigquery.py`'s docstring.
- R5.2 WHEN ADR 0115 and ADR 0116 are accepted THE SYSTEM SHALL mark ADR 0046
  `amended by` 0115 and ADR 0053 `superseded by` 0116, as `test_adr_headers.py` requires.
- R5.3 WHERE the README or the docs site says that floats are held to a tolerance on
  BigQuery, or that a BigQuery build does not repeat itself, THE SYSTEM SHALL say instead
  that both warehouses reproduce to the last digit.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| Ordered aggregate calls through the macros | 35 in 13 models (32 sums, 2 means, 1 correlation), and 4 sums in 2 singular tests | `grep -rhoE 'fo_(sum\|avg\|corr)_in_order\(' dbt/models dbt/tests` (C1) |
| DuckDB compile | identical to `main`'s for every node, on `ci` and `dev` | `dbt compile` on both, `diff -r` of `target/compiled` (R1.4) |
| DuckDB fixture build | all unit tests pass, as many as `main` has plus R3.2's | `.agentic/gates` |
| BigQuery unit tests, suffixed complete build | every one passes, 0 fail, 0 error (`main`: 220 pass, 4 fail) | AGENTS.md's unit-test commands, recorded on #139 (R3.1) |
| BigQuery against DuckDB, real season | every relation of the selector exact, floats included (#135 had 0 relations beyond 1e-9, and ADR 0053's tolerance hid the rest) | `compare_bigquery.py --suffix _139` (R4.1) |
| BigQuery against itself | the 13 models and their descendants exactly equal across two builds (spike: 2 of 29 differed) | R4.2 |
| Bytes billed | recorded, not a gate: each of the 13 models' bytes billed beside a dry run of `main`'s compiled SQL for it, which is free. An order key the native aggregate did not read can add columns. Any model that bills more is explained on #139. The full build was about 56 GB (#137, C12) | `INFORMATION_SCHEMA.JOBS_BY_USER` and the dry runs, recorded on #139 |
| Build time | recorded, not a gate: the 13 models' summed time is expected within 60 s of `main`'s, from about 3 s per 200,000 folded groups (C5). Whole builds vary by 300 s between runs (#137: 1,440 and 1,753 s), so the whole build is no measure of it | dbt's `run_results.json`, recorded on #139 |
