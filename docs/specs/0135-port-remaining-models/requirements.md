# Every SQL model on both warehouses: the 26 models outside the BigQuery slice — requirements

Issue: #135 · Tier: M · Status: draft

## Problem

The spike (#130) ported a slice of the project to the two-warehouse rule of ADR 0051, and
later specs kept that slice ported as it grew to 48 models. The other 27 models are still
written for DuckDB alone. One is the lineup solver's Python model, whose BigQuery runner is
#137. The other 26 are SQL models that BigQuery refuses as written: counted with the rule
test's own patterns at `8585a4e`, they hold `filter (where …)` 51 times in 8 models, an
ordered `sum` 15 times in 9, `bool_or` 11 times in 5, `unnest(` 10 times in 6, `::` 10
times in 2, and six more kinds (design C3). Twelve hold none. Nine singular tests outside
the slice have refused constructs too (C5). #136 put the last raw endpoints on BigQuery,
so nothing upstream blocks these models any more. Three of them read the solver's output
and still cannot run there (C2).

While grounding this spec, one model turned out to give a different number on each
warehouse whatever the port does. `stg_espn__transactions` dates a transaction through a
cast that follows the session's time zone, and on the owner's machine 28 of 737
transactions come out a day early (C9). The owner chose on 2026-10-23 to fix that first,
as its own issue, #188. **This port depends on #188.** Its baseline is a real warehouse
rebuilt after #188 merges, so that DuckDB and BigQuery agree on those rows and the
comparisons below hold with no exception.

## Goals

- Every SQL model, singular test and macro of the project is written once for both
  warehouses, and a test holds the whole project to it, not just a selection.
- Everything that can run on BigQuery today builds there from the real season, passes its
  tests, and matches the DuckDB build: non-float values exactly, floats within ADR 0053's
  tolerance.
- The owner's DuckDB warehouse, as rebuilt after #188, does not change by a digit.
- The models that wait on the solver (#137) are already ported, so that #137 only has to
  decide where Python runs.

## No-gos

- The lineup solver's Python model, and building the three models that read it on
  BigQuery. Those belong to #137.
- Changing what any model computes. A difference between the warehouses that needs a
  model's logic changed goes to the owner as a finding, as the spike's tie-break did.
- The transaction-date fix, its tests and its ADR. All of that is #188.
- Missing tie-breaks (#141), float aggregates whose order BigQuery cannot fix (#139), and
  staging unit tests that cannot get a JSON fixture on BigQuery (#138). Where this port runs
  into one of them, it is recorded on that issue.
- Rewriting the 7 unit tests whose fixtures are DuckDB SQL (`format: sql`) so that they run
  on BigQuery. They are reported as not runnable (R4.5).
- The production loader (#140), BigQuery in CI or in `.agentic/gates`, sqlfluff on the
  BigQuery SQL.
- Renaming `bigquery_slice` or `scripts/compare_bigquery_slice.py` (ADR 0096).
- The fixtures, `scripts/make_fixtures.py`, `scripts/make_multi_fixtures.py`, the capture
  views and `fo_captures`, `docs/examples/expected_on_fixtures.yml`, and
  `dbt/plants/_empty_in_ci.yml`. Spec 0178 is changing some of them in parallel. None is
  expected to need a change here, and if one does, that is raised first.

## Rabbit holes

- **Constructs the patterns cannot see.** The spike found contract types in YAML, a date
  subtraction, `median` and a bare column in HAVING only by running SQL over no rows on
  BigQuery. → The empty build (R4.1) is the proof, as in the spike. Two differences in
  meaning are written into the design's table now, because neither an empty build nor a
  pattern finds them (C7, C8). `greatest` with a null argument: DuckDB skips the null,
  BigQuery returns null. An ascending sort over nulls: DuckDB puts them last, BigQuery
  first.
- **The 2.3 MB roster payloads (rule 1).** `stg_espn__roster_entry_slots` unnests three
  levels of the roster view for 2,348,532 rows. Moving `unnest` into the FROM clause can
  change DuckDB's plan. → Its build time and peak memory are recorded against the
  baseline's (R3.4), as `stg_espn__roster_entries`' were in the spike.
- **An exact column fed by a float.** `rec_fantasy__category_wins_added` compares a hash
  draw against a fraction built from float replacement levels, and rounds stat values to 9
  places. A last-digit float difference could flip a count. → Not prevented. If the
  comparison shows it, it is explained from the float difference and taken to the owner
  (R4.6). The spike's `fct_matchup_category_scores` has the same shape and compared equal.
- **Comparing everything on BigQuery costs money.** → Every query stays under the target's
  10 GB cap. Tables are read back through the client, which is not billed, and bytes billed
  are reported (R4.7).

## Requirements

### R1. What builds on BigQuery

The selector says what runs on BigQuery. It now names what is left out rather than what
is in (ADR 0096).

- R1.1 THE SYSTEM SHALL define `bigquery_slice` in `dbt/selectors.yml` as every model and
  seed of the project except `int_fantasy__optimal_lineups` and every model downstream of
  it, with `indirect_selection: cautious`.
- R1.2 THE SYSTEM SHALL have that selector select 71 models (39 tables, 30 views, 2
  ephemeral), 7 seeds and no Python model, at the base commit. The counts are retaken if
  `main` moves before the build.
- R1.3 WHEN a SQL model is added that does not read the solver's output THE SYSTEM SHALL
  select it with no edit to the selector.
- R1.4 THE SYSTEM SHALL have no selected test read a model the selector leaves out.

### R2. The rule holds for the whole project

- R2.1 THE SYSTEM SHALL fail `test_dbt_portable_sql_rule.py` when any SQL model or singular
  test of the project, or any project macro one of them reaches, holds a refused construct
  outside a `duckdb__` form. The files to scan come from the manifest's every SQL model and
  singular test, not from the selector, so the three solver readers are held too.
- R2.2 THE SYSTEM SHALL add to that test's patterns the constructs this port finds that
  BigQuery refuses: `md5(`, `concat_ws(`, and each one the empty build of R4.1 turns up.
- R2.3 THE SYSTEM SHALL have `test_dbt_ordered_aggregate_rule.py` accept a float aggregate
  written through `fo_corr_in_order` as ordered, as it does `fo_sum_in_order` and
  `fo_avg_in_order`.
- R2.4 THE SYSTEM SHALL have every contract `data_type` and seed `column_types` entry of the
  project name a type both warehouses accept, or switch on `target.type`. The tests that
  check this for the slice check every model and seed.
- R2.5 THE SYSTEM SHALL state in AGENTS.md that every SQL model is written once for both
  warehouses. README's BigQuery section SHALL say that the target builds every model but the
  solver and its three readers, with the unit tests excluded (R4.1). Its sentence "the other
  models are not ported and fail there" is no longer true.

### R3. DuckDB is unchanged

- R3.1 WHEN the real season is built on `dev` from the ported models THE SYSTEM SHALL
  produce a warehouse equal, over every relation, to the baseline built from `main` once
  #188 has merged, as `scripts/compare_warehouses.py BASE NEW --strict-columns` decides.
- R3.2 THE SYSTEM SHALL leave the DuckDB type of every column of every relation as it was.
- R3.3 `.agentic/gates` SHALL pass. The CI warehouse built from the fixtures SHALL equal the
  one built before the port, every relation (`compare_warehouses.py --strict-columns`).
- R3.4 THE SYSTEM SHALL record the real build's wall time and peak memory, and those of
  `stg_espn__roster_entry_slots`, against the baseline's. IF peak memory rises by more than
  a quarter THEN the build SHALL stop and go to the owner before merge.
- R3.5 IF #188 has not merged THEN THE SYSTEM SHALL NOT take the baseline of R3.1 or run
  the comparisons of R4. The port's code may be written before then; it is rebased onto
  `main` once #188 lands.

### R4. The same numbers on BigQuery

- R4.1 WHEN the selector is built on `bq` with `--empty --exclude-resource-type unit_test`
  THE SYSTEM SHALL complete without an error from BigQuery. Unit tests are left out of both
  builds because dbt runs a model's unit tests before the model, and the 7 with DuckDB-SQL
  fixtures, along with the staging tests of #138, cannot run there. They are run on their
  own by R4.5.
- R4.2 WHEN the selector is built on `bq` from the real season's uploaded captures, with
  `--exclude-resource-type unit_test`, THE SYSTEM SHALL build every selected model and
  seed, and every selected data test SHALL pass, with `anonymize: false`.
- R4.3 WHEN the two builds are compared with `scripts/compare_bigquery_slice.py` THE SYSTEM
  SHALL exit 0 over every relation of the selector, seeds included: equal row counts,
  non-float columns equal as multisets, float columns joined on the declared unique key and
  equal within ADR 0053's tolerance. Both builds are of the real season after #188 has
  merged (R3.5), so `stg_espn__transactions` and what reads it are held like any other
  relation. The script lists models only today, so it SHALL be taught to list the selected
  seeds too (design review F4).
- R4.4 THE SYSTEM SHALL compare `stg_espn__roster_entry_slots` exactly, so that the roster
  view's `eligibleSlots`, which the comparison does not read as a nested field, comes under
  comparison through the model that reads it (the note on #135, 2026-10-15).
- R4.5 WHEN the unit tests of the 23 newly selected models are run on `bq` THE SYSTEM SHALL
  report each one as passed, failed or not runnable, with dbt's error. A failed one is a
  difference, explained before the work is done. A not-runnable one is recorded on #138.
- R4.6 IF the comparison finds a difference in a non-float column THEN THE SYSTEM SHALL NOT
  change what a model computes to remove it without the owner. The difference is traced to
  its cause (a tie broken differently, #141; a float-fed comparison; a construct whose
  meaning differs) and brought to the owner with the rows.
- R4.7 THE SYSTEM SHALL report bytes billed per model and in total, for models and data
  tests, from `run_results.json`. No query SHALL be refused by the 10 GB cap.

### R5. The models that read the solver

- R5.1 THE SYSTEM SHALL port `int_fantasy__lineup_category_totals`, `fct_lineup_decisions`
  and `fct_lineup_decision_categories` and their singular tests under the rule. R2.1 holds
  them, and R3.1 holds their numbers on DuckDB.
- R5.2 WHEN an empty table with the solver's columns and types stands on BigQuery in place
  of `int_fantasy__optimal_lineups` THE SYSTEM SHALL build the three readers there with
  `--empty`, with no error from BigQuery, and SHALL then drop that table. This runs their
  SQL over no rows, which is what ADR 0051 counts as accepted. The table is created by DDL
  and holds no data, so nothing new is uploaded.
- R5.3 THE SYSTEM SHALL comment on #137 that these three are ported and shown to run over
  no rows on BigQuery but not yet built from real rows, and that its decision is what brings
  them there.

## Expected values

Counts are from `data/warehouse_main_ac0e2ac.duckdb` (built 2026-10-19) unless stated.
Two PRs that touched the solver chain (#164) merged after it, and #188 will change the
rows of `stg_espn__transactions`, `int_fantasy__transactions` and `fct_transaction_impact`
that it fixes. So the binding baseline is the build of task 1, after #188, and the counts
are retaken there.

| Check | Expected | How to verify |
|---|---|---|
| Selector | 71 models (39 table, 30 view, 2 ephemeral), 7 seeds, 0 Python | `dbt ls --selector bigquery_slice --resource-type model/seed` (C1) |
| Tests the selector takes | 436 data tests, 187 unit tests | `dbt ls … --resource-type test/unit_test` (C1) |
| Models left out | `int_fantasy__optimal_lineups`, `int_fantasy__lineup_category_totals`, `fct_lineup_decisions`, `fct_lineup_decision_categories` | the same, against `dbt ls` of all models (C2) |
| Refused constructs left, whole project | 0 | `test_dbt_portable_sql_rule.py` (R2.1) |
| Newly built relations on BigQuery | 23, holding 3,089,233 rows in all; the largest are `stg_espn__roster_entry_slots` 2,348,532 · `int_fantasy__lineup_options` 437,559 · `int_fantasy__candidate_day_values` 198,363 · `fct_player_category_value` 73,553 | `compare_bigquery_slice.py` row counts (C4) |
| Float relations among them | 13, each with a declared unique key | the comparison's float join (C6) |
| DuckDB after the port | equal to task 1's baseline over every relation | R3.1 |
| CI warehouse | equal before and after, every relation | R3.3 |
| Any BigQuery query | at most 10 GB billed | R4.7 |
| Bytes billed by one build | the slice billed 5.35 GB (models 2.51, data tests 2.85). This build is expected to bill more, by the new data tests and `stg_espn__roster_entry_slots`' read of the roster view (256 MB for `stg_espn__roster_entries`). Reported, not bound | R4.7 (C18) |
