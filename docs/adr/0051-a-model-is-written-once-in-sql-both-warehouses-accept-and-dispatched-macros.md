# 0051. A model is written once: SQL both warehouses accept, and a dispatched `fo_*` macro for the rest

- Status: accepted
- Date: 2026-10-11
- Spec: [0130-bigquery-spike](../specs/0130-bigquery-spike/design.md) · Issue: #130

## Context

The project was built on the belief that moving to BigQuery touches only
`dbt/macros/json.sql`. Asked on 2026-10-11 by dry run, BigQuery refused 21 of 47
constructs the project uses, and most are written in models: `filter (where …)` 69 times
in 16 files, `unnest(…)` in a SELECT list 32 times in 18, `::` 24 times in 9, ordered
float aggregates (ADR 0046) in 11 model files, the types `varchar` and `double`,
`try_cast`, `generate_series`. Something has to say how a model is written from now on,
and DuckDB stays a working warehouse throughout: it is what CI and the fixtures build on.

Some refused constructs have a spelling both warehouses accept (`cast(x as integer)`,
`count(case when c then 1 end)`). Some have none (`double` against `float64`, `unnest`,
`try_cast` against `safe_cast`). One has no BigQuery form at all: an aggregate cannot be
given an order.

dbt ships cross-database macros (`dbt.safe_cast`, `dbt.type_float`, `dbt.type_string`).
Their DuckDB output is not what the models write today in every case:
`dbt.type_float()` is `float` unless the adapter overrides it, and `float` in DuckDB is
32-bit.

## Decision drivers

- One definition of each model. Two would drift.
- The DuckDB warehouse must not change by a digit, and that must be checkable.
- A reader of a model should see SQL, not a macro call per line.
- A construct with no BigQuery form must be visible where it is used.
- Whatever the rule is, a test can enforce it.

## Considered options

1. **SQL both warehouses accept where it exists; otherwise a dispatched `fo_*` macro**
   with a DuckDB form and a BigQuery form.
2. **dbt's cross-database macros first**, `fo_*` only where dbt has none.
3. **Everything refused goes through a macro**, including casts and `filter`.
4. **Transpile dbt's compiled DuckDB SQL** to BigQuery with SQLGlot; models unchanged.
5. **A model file per warehouse.**

## Decision

Chosen by the owner on 2026-10-11, going through the spec's decisions: **option 1**.

A model contains none of the constructs BigQuery refuses. Where both accept a spelling,
the model uses it as plain SQL. Otherwise it calls a macro in `dbt/macros/portable.sql`
or `json.sql` that dispatches on the adapter; the DuckDB form emits what the model has
today. There is no `default__` form. A pytest scan fails on a refused construct in a
ported file, as `test_dbt_json_rule.py` does for JSON. dbt's own cross-database macros
are used only where their DuckDB output has been checked to be the SQL already there.

Option 2 changes DuckDB's numbers through `type_float` unless every macro is checked
first, and then it is option 1. Option 3 hides ordinary SQL behind names for no gain on
either warehouse. Option 4 cannot translate what has no translation (the ordered
aggregate, `from_json` with a structure, JSON key order), and its output is not a dbt
model. Option 5 is every change made twice.

"Accept" means run, not parse: a JSON path ending in `[*]` passes BigQuery's dry run and
fails when executed. So the list of refused constructs is kept by a test and completed
by building the slice on BigQuery over no rows (dbt's `--empty`), not by reading.

The spike (spec 0130) is the test of this: if porting 30 models shows the macro list
growing without end, or DuckDB's warehouse cannot be kept equal, this is revisited before
the other 27 are touched.

## Consequences

- Good: `filter`, `::` and most casts become plain SQL and need no macro.
- Good: the rule is mechanical, so the remaining models can go to the implementer.
- Bad / accepted cost: `count(case when c then 1 end)` reads worse than
  `count(*) filter (where c)`, 69 times.
- Bad / accepted cost: `unnest` moves from the SELECT list into the FROM clause through
  a macro, in 18 files. It is the least readable change and the one most likely to move
  DuckDB's plan (AGENTS.md rule 1).
- Bad / accepted cost: `fo_sum_in_order` and `fo_avg_in_order` state an order DuckDB
  uses and BigQuery ignores. ADR 0046 holds on DuckDB only; see ADR 0053.
- Bad / accepted cost: a construct with no shared shape forces a model to be rewritten
  on DuckDB as well. `stg_espn__pro_games` is the known case: it parses a DuckDB `MAP`,
  which BigQuery does not have.
- Bad / accepted cost: sqlfluff lints the DuckDB compilation only.
- Follow-ups: AGENTS.md gains the rule when the spike merges; the 27 other models are
  ported under it; `md5` and `to_timestamp`, which the slice does not contain, get their
  forms then.
