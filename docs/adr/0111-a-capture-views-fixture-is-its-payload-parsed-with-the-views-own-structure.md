# 0111. A capture view's fixture is its payload, parsed with the view's own structure

- Status: proposed
- Date: 2026-10-29
- Spec: [0138-unit-tests-on-bigquery](../specs/0138-unit-tests-on-bigquery/design.md) · Issue: #138

## Context

Four capture views parse their files into a declared structure as they read them (ADRs
0068, 0101, 0102). The columns they give are typed: on DuckDB as STRUCTs, lists and
MAPs, on BigQuery as STRUCTs and ARRAYs, with a map as an array of key-value structs. A
unit test of a model that reads such a view mocks the view. Today its 14 fixtures do that
in DuckDB SQL: `from_json(…, '<DuckDB type>')`, `::JSON`, `::BIGINT` (spec 0138, C16).
BigQuery refuses all of these.

## Decision drivers

- The fixture's columns and types must be the view's, on each warehouse, and must not
  drift from the view when its structure changes.
- A fixture should read like what lands, so a case can be checked against a real
  capture.
- No parser of BigQuery type strings.

## Considered options

1. **The payload, through the view's structure.** The fixture gives each capture's keys
   and payload text to `fo_capture_rows(source, endpoint, captures)`. That macro parses
   the payload with the structure the view itself uses, which moves into
   `fo_capture_structure(source, endpoint)` so both read one copy.
2. **Each column as a typed value, through portable macros.** The fixture keeps today's
   shape, one value per declared column, with `fo_json_parse(…)` in place of
   `from_json` and the structure repeated in each fixture.
3. **Dict fixtures with typed columns.** Each declared column is given as JSON in a dict
   row, and a `safe_cast` override parses it into the column's type, read from the
   warehouse.

## Decision

Chosen by the owner on 2026-10-29, as recommended: **option 1**. It was tried on both
warehouses, on the schedule and on the roster with its `stats` map (C13).

Option 2 repeats each structure in every fixture, 14 copies of 4 structures, and nothing
keeps them equal to the views. Option 3 needs the override to read BigQuery's
`ARRAY<STRUCT<…>>` type strings back into a structure, and it gives the columns one by
one rather than the capture as it lands.

## Consequences

- Good: a fixture is a capture. Adding a field to a view's structure reaches every
  fixture of that view without an edit.
- Good: the BigQuery parse a test runs is the view's own expression, so the test checks
  it.
- Bad / accepted cost: the structures leave their view files for a macro file, and their
  field comments go with them. Each view keeps its comment on why it parses.
- Bad / accepted cost: a payload in a fixture is one long JSON string inside a Jinja call
  inside YAML.
