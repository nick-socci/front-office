# Rule 1 is checked: no payload is carried into an unnest — requirements

Issue: #134 · Tier: M · Status: draft

## Problem

AGENTS.md rule 1 (project `payload` away before any `unnest`) is the rule that cost a 24 GB
out-of-memory, and nothing in the gates holds it. A build on the fixtures passes either way,
because the fixtures are small. Two other AGENTS.md rules have a test (#79, ADR 0046).

The issue's picture of `main` (2026-10-11) is out of date. The two models it names have been
in the header form since #130 and #135, and `stg_mlb__games` reads no payload since #156
(design.md, C2). On `main` no unnest carries a payload (C1, C5). What is left is the check,
so that the next model written the old way fails CI.

Since spec 0150, only seven endpoints still have a `payload` column: matchups, pro_schedule,
settings, teams, transactions, MLB players and the id map. On the real season they run from
6 KB to 4.3 MB a capture (C3, C4). The heavy endpoints are parsed into a declared structure
and are already held by the plan-shapes gate (ADR 0102).

## Goals

- A model or test whose DuckDB plan carries a `payload` column into an unnest fails the
  gates, naming the node.
- The check is shown to fail on the forms the rule forbids, including the earlier forms of
  the models #134 names, and to pass the header form.
- The check cannot be switched off without anyone noticing, by a DuckDB upgrade or by an
  endpoint losing its fixture captures.

## No-gos

- No model, macro or singular test changes. Nothing on `main` violates the rule (C5), so
  the warehouse is unchanged by construction.
- No exemption mechanism for a payload carry (ADR 0106).
- Delim joins and CTEs over payload endpoints are not in scope: ADR 0102 decided that a
  gathering operator over a small endpoint is not a failure. 21 nodes have one (C9).
- No text-based SQL test (ADR 0106, option 2).
- Rules 4 and 5 are not in scope (the issue's constraint).
- A large column that is not named `payload` (a renamed payload, a parsed list) is not
  detected (ADR 0106, consequences).
- BigQuery is not checked: the cost of a carried payload is DuckDB memory.

## Rabbit holes

- **The plan's format.** `Projections` is a string when an operator projects one column and
  a list otherwise (C6). The unnest shows up as `UNNEST`, as an `INOUT_FUNCTION` named
  `unnest`, or under a `CROSS_PRODUCT`, depending on the shape (C6, C7, C11). → All three
  are handled. A probe runs on every gate (R3.1), so a format change fails loudly instead
  of passing quietly.
- **Nodes that cannot be explained outside dbt.** `int_fantasy__optimal_lineups` calls the
  solver, which exists only on dbt's connections (C5). → The check registers it from
  `dbt/python_modules/fo_duckdb_functions.py`, the same names and types the plugin uses.
- **The real warehouse.** `data/warehouse.duckdb` (2026-10-11) predates the capture views,
  and 46 of the 142 readers do not bind against it (C10). → The real-season check runs
  against a current real build (task 7). Nothing the check reads comes from row counts.

## Requirements

### R1. Find the readers of a payload

- R1.1 THE SYSTEM SHALL treat as a payload capture view every model whose `raw_code` calls
  `fo_captures` with two arguments, and take its source and endpoint from them.
- R1.2 THE SYSTEM SHALL treat as a payload reader every model and test that reaches a
  payload capture view through views and ephemerals alone, the same way it finds heavy
  readers. The payload capture view itself is not a reader.
- R1.3 IF a payload view's (source, endpoint) pair has no capture in the CI warehouse THEN
  THE SYSTEM SHALL fail, naming the pair. The pair is compared, not the endpoint alone: a
  future `espn/players` must not count as covered by `mlb/players`' captures.
- R1.4 IF a payload capture view in the CI warehouse has no column named `payload` THEN THE
  SYSTEM SHALL fail, naming the view. The check keys on that name.

### R2. Fail a payload carried into an unnest

- R2.1 WHEN the gate explains a payload reader's compiled SQL THE SYSTEM SHALL find every
  operator that repeats its input once per element of a list, together with that input:
  - an `UNNEST` operator, or an `INOUT_FUNCTION` whose `Name` is `unnest`: all its children
    (a list that depends on the row, C6);
  - a `CROSS_PRODUCT` or a join (not a delim join, and not a semi, anti or mark join, which
    repeat nothing) with an unnest anywhere under one child: its other children. This is a
    list that does not depend on the row, such as a constant or `fo_int_series` over
    constants, with or without a filter between the join and the unnest (C11, C12).
- R2.2 IF one of those inputs emits a column whose name or expression contains the word
  `payload` THEN THE SYSTEM SHALL report a problem naming the node, the operator and the
  payload endpoints the node reads. What an input emits is its `Projections`; for an
  operator without them (a filter, a join) it is what its children emit, the left child
  alone for a semi, anti or mark join.
- R2.3 THE SYSTEM SHALL read `Projections` given as a string or as a list.
- R2.4 THE SYSTEM SHALL accept no register entry for such a problem: `plan_shapes.yml`
  keeps its two operators, `delim_join` and `cte`.
- R2.5 THE SYSTEM SHALL register the lineup solver on its DuckDB connection from
  `fo_duckdb_functions` (its `NAME`, `ARGUMENTS` and `RETURNS`), so that every reader can
  be explained.
- R2.6 IF a payload reader's compiled SQL cannot be explained THEN THE SYSTEM SHALL fail,
  naming the node (as it does for heavy readers today).
- R2.7 THE SYSTEM SHALL print every problem, not just the first, and say how many payload
  readers and unnest operators it examined.

### R3. The check cannot go quiet

- R3.1 WHEN the gate runs THE SYSTEM SHALL explain three probe queries over one payload
  capture view, each carrying its payload into an unnest: a list column of a header (an
  `UNNEST`), a constant list (a `CROSS_PRODUCT`), and a constant list with a WHERE on its
  element (a `FILTER` between). IF R2's detector does not flag each one THEN THE SYSTEM SHALL
  fail, naming the probe and saying the plan format has changed.
- R3.2 THE SYSTEM SHALL keep finding heavy-endpoint problems exactly as before (ADR 0102):
  the new checks are added beside them, not in place of them.

### R4. Shown to fail on the forbidden forms

- R4.1 THE SYSTEM SHALL have unit tests whose plans come from explaining SQL in an in-memory
  DuckDB, over a table with a JSON `payload` column. These forms must be flagged:
  (a) a payload field beside a select-list `unnest` (`stg_espn__teams` before #135);
  (b) an unnest of an expression over `payload` in the FROM clause, with payload fields
  beside it (`stg_espn__scoring_categories` at fe591f1);
  (c) the same with only `fetched_at` beside it (`stg_mlb__games` at fe591f1, the form that
  ran the real build out of memory in spec 0130);
  (d) a header that keeps `payload`, used beside the unnest of a list;
  (e) `payload` beside the unnest of a list that does not depend on the row (a constant
  list, and `generate_series` over constants), planned as a `CROSS_PRODUCT`;
  (f) form (e) with a WHERE on the unnested element (a `FILTER` between the cross product
  and the unnest), with a filter on the payload side instead, and written as
  `inner join … on true`;
  (g) `payload` joined on a condition to rows unnested in a subquery (a `HASH_JOIN`).
- R4.2 THE SYSTEM SHALL have unit tests showing that these pass: the header form; a header
  that keeps a `payload` column the unnesting SELECT never reads; a constant list unnested
  beside small columns only; and payload rows filtered by a semi join against an unnested
  list (`where … in (select unnest(…))`).
- R4.3 THE SYSTEM SHALL have unit tests for R1.1 to R1.4, R2.3, R2.6 and R3.1 on
  hand-written manifest nodes and plan JSON, as `test_check_plan_shapes.py` does today.

### R5. The rule says where it is held

- R5.1 THE SYSTEM SHALL say in AGENTS.md rule 1 that the plan-shapes gate holds it, and
  what it cannot see (a renamed payload).
- R5.2 THE SYSTEM SHALL describe the payload check in the module docstring of
  `check_plan_shapes.py`, in the step name in `.agentic/gates` and in the CI workflow, and in
  the comment heading `dbt/plan_shapes.yml` (no exemption for it).

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| Payload capture views | 7: matchups, player_id_map, players, pro_schedule, settings, teams, transactions | the gate's summary line |
| Payload readers and unnest operators on the CI warehouse | 142 and 211 (C5); they change as models are added, and are reported, not asserted | the gate's summary line |
| Payload carries on `main`, CI warehouse | 0 | `uv run python scripts/check_plan_shapes.py --db dbt/ci.duckdb` exits 0 |
| Readers that cannot be explained | 0 (the solver registered) | the same run |
| Payload carries on a current real-season build | 0 | task 7 |
| The probe (R3.1) | flagged on every run | the same run; a unit test breaks the detector and sees the gate fail |
| Files changed under `dbt/models`, `dbt/macros`, `dbt/tests` | none | `git diff --stat main -- dbt/models dbt/macros dbt/tests` |
| Real-season warehouse | unchanged, by construction (no model changes) | the row above |
