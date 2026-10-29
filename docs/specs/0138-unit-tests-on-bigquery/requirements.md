# Every unit test runs on both warehouses — requirements

Issue: #138 · Tier: M · Status: draft

## Problem

Every model is written once for DuckDB and BigQuery (ADRs 0051, 0105), but 45 of the 223
unit tests cannot run on BigQuery because of how their fixtures are written (design.md,
C3, C4). 20 give the manifest as `source('raw', 'captures')`, which only DuckDB reads. 9
give a JSON value in a form BigQuery will not take. 16 are written in DuckDB SQL. So
BigQuery's forms of the JSON macros and of the capture views' parses have no unit tests
on BigQuery. A comparison of whole builds is all that checks them, and it sees only the
cases the real season happens to hold. The list grows: #135, #194 and #141 each added
tests that cannot run there.

The owner chose on 2026-10-29 that every unit test is to run on both warehouses, rather
than marking the staging tests DuckDB-only.

## Goals

- Each unit test (223 today, 224 with R4.2's) runs on both warehouses from one definition,
  and passes on both. The exceptions are the four tests #139 owns (last-digit float order).
- A new fixture that uses a construct the portable rule knows BigQuery refuses fails the
  gates, with the test named. A construct the rule does not know is found by the next
  BigQuery run of the unit tests (ADR 0110), which is part of any build that adds a new
  form of fixture.
- How to write a fixture for both warehouses, and how to run the unit tests on
  BigQuery, are written down where the next author looks.

## No-gos

- No expected rows change, no unit test is deleted, and none is tagged or skipped as
  DuckDB-only. A rewritten fixture gives the model the same rows as the one it replaces
  (R1.4).
- #139's four tests are not fixed, skipped or given a tolerance. They are #139's.
- No model's SQL changes. The capture views take their structures from a macro, but they
  compile to the same SQL as before (R3.3).
- BigQuery's raw layer does not change: no `raw.captures` on BigQuery. That table belongs
  to the production loader (#140).
- CI does not connect to BigQuery. Credentials are the owner's decision (ADR 0110). A
  BigQuery run of the unit tests stays a by-hand check, recorded on the issue.
- The populated default BigQuery datasets are not rebuilt. They lack the solver function
  and `int_fantasy__optimal_lineups` (C2), which is why 32 tests error there. That is
  reported to the owner and is not part of this work.

## Rabbit holes

- **dbt renders a unit test's `rows` when it parses the YAML, before the project's macros
  exist.** A `{{ fo_… }}` call there fails as undefined (C6). → A fixture that calls a
  project macro wraps the call in `{% raw %}…{% endraw %}`, which leaves it to be
  rendered at compile time with the full context (ADR 0112).
- **DuckDB's cast from JSON to a struct refuses keys the struct does not name** (C12). A
  payload-shaped fixture has such keys, as the real files do. → The DuckDB form uses
  `from_json` with a JSON structure, which ignores them, as the view's `read_json` does.
- **BigQuery unescapes the backslashes in a string literal.** JSON text with `\"` in it
  would reach `parse_json` broken (C11). → The `safe_cast` override builds the literal
  itself rather than reusing dbt's (R4.2).
- **YAML changes values it reads unquoted.** PyYAML reads `on` and `yes` as `true` (C15).
  → JSON stays JSON text in a string, never a YAML mapping (ADR 0113).
- **dbt reads the columns of every dict-fixture input from the warehouse.** On BigQuery
  that needs a complete build of the branch, and the default datasets are not one (C2).
  → The BigQuery run goes against suffixed datasets, built `--empty` from the branch
  (R6.2). That bills nothing but the solver function's image build.

## Requirements

### R1. Every unit test runs on both warehouses

- R1.1 WHEN the unit tests run on DuckDB (`dbt build --target ci`, as the gates run
  them) THE SYSTEM SHALL pass all 224.
- R1.2 WHEN the unit tests of the `bigquery` selector run on BigQuery against a complete
  build of the branch (R6.2) THE SYSTEM SHALL pass every one except the four #139 tests,
  and SHALL give no error.
- R1.3 THE SYSTEM SHALL keep each unit test's name, model and `expect` block as they were.
- R1.4 WHEN a fixture is rewritten THE SYSTEM SHALL give, on DuckDB, the same rows as the
  fixture it replaces: equal both ways under `except all`, with the same column names
  and types. Checked once per rewritten fixture during the build, and recorded on #138.

### R2. The manifest is named by the target

- R2.1 WHEN a unit test gives the loader's manifest THE SYSTEM SHALL name it with one
  `given` entry that resolves to `source('raw', 'captures')` on DuckDB and to
  `source('raw', 'api_responses')` on BigQuery (ADR 0114).
- R2.2 IF a unit test names either source literally THEN the gates SHALL fail and name
  the test.

### R3. A capture view's fixture is its payload

- R3.1 THE SYSTEM SHALL provide `fo_capture_rows(source_name, endpoint, captures)`. It
  gives the rows of a capture view: each capture's manifest keys, and each top-level
  field of the view's declared structure parsed from that capture's payload text. The
  columns have the view's names and types on each warehouse (ADR 0111).
- R3.2 WHEN a payload holds a key the structure does not declare, or lacks a field the
  structure declares, THE SYSTEM SHALL give what the view gives for the same file on the
  same warehouse. The warehouses differ here today, and this work does not change that:
  for an absent list or object DuckDB gives null, while BigQuery's parser gives an empty
  array or a struct of nulls (design.md, C20).
- R3.3 THE SYSTEM SHALL keep each of the four declared structures in one place, which
  both the view and `fo_capture_rows` read. Each view SHALL compile to the same SQL as on
  `main` on both targets.
- R3.4 IF a SQL fixture of a capture view that declares a structure does not go through
  `fo_capture_rows` THEN the gates SHALL fail and name the test.

### R4. A JSON value in a dict fixture stays JSON text

- R4.1 WHEN a dict or csv fixture gives a JSON column a string THE SYSTEM SHALL give the
  column that JSON value on both warehouses (ADR 0113).
- R4.2 WHEN that text holds double quotes, apostrophes, backslashes or escaped
  characters THE SYSTEM SHALL give the column the same JSON value as when the text has
  none. A new unit test of `stg_mlb__players` holds this: names with an apostrophe
  (`Travis d'Arnaud`), an escaped double quote and a backslash come out exactly as MLB
  gives them.
- R4.3 WHILE a fixture value is for a column that is not JSON THE SYSTEM SHALL cast it as
  dbt does today.

### R5. SQL fixtures are portable

- R5.1 THE SYSTEM SHALL hold no construct BigQuery refuses in any SQL-format fixture,
  nor in any project macro a fixture calls, directly or through another macro, nor in the
  `safe_cast` override. The list is the one `test_dbt_portable_sql_rule.py` holds for
  models and macros.
- R5.2 THE SYSTEM SHALL add to that list the construct found here: a WHERE in a query
  with no FROM. It applies to models and macros as well as fixtures. (Amended 2026-10-29:
  a comma join was dropped; see design.md, Amendments.)
- R5.3 IF a SQL fixture holds a refused construct THEN the gates SHALL fail and name the
  test and the construct.
- R5.4 WHEN a fixture needs a project macro (a portable type, an integer series,
  `fo_capture_rows`) THE SYSTEM SHALL call it inside `{% raw %}…{% endraw %}` in the
  YAML (ADR 0112).

### R6. Written down and run

- R6.1 AGENTS.md's dbt gotchas SHALL say how to write a fixture for both warehouses
  (R2.1, R3.1, R4.1, R5.4), and that dbt renders `rows` at parse time.
- R6.2 AGENTS.md SHALL give the commands that run the unit tests on BigQuery: into
  suffixed datasets, `dbt seed`, the function, `dbt run --empty`, then
  `dbt test --resource-type unit_test --selector bigquery`, all with the same
  `fo_schema_suffix`.
- R6.3 Each new gate rule (R2.2, R3.4, R5.2, R5.3) SHALL have a test showing it fail on
  a planted example and pass on the allowed spelling.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| Unit tests on DuckDB | 224 pass (223 and R4.2's) | `.agentic/gates` (its `dbt build --target ci`) |
| Unit tests on BigQuery, complete suffixed build of the branch | 220 pass. 4 fail: `category_scales_take_a_side_denominator_in_matchup_order`, `reported_margins_sum_a_denominator_in_component_order`, `category_wins_by_group_measure_the_slope_over_measured_pairs`, `category_wins_by_group_take_the_correlation_in_player_order`. 0 errors | R6.2's commands, on #138 |
| The same run, before this work (C3) | 174 pass, 4 fail, 45 errors | already recorded (C3) |
| Compiled SQL of the 11 capture views | identical to `main`'s, on `ci` and on `bq` | `dbt compile` on both branches, `diff` |
| Rows of each rewritten fixture on DuckDB | equal to the old fixture's, both ways | R1.4's check, on #138 |
| Bytes billed by the BigQuery unit-test run | 0 | `bq ls -j`, `totalBytesBilled` (C5) |
| Expected rows changed, tests removed | 0, 0 | `git diff main -- dbt/models` changes no `expect:` block and removes no test name; one test is added (R4.2) |
