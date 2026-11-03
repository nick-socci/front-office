# 0118. The loader reduces a heavy capture to its declared structure, read from the one macro file

- Status: accepted
- Date: 2026-11-02
- Spec: [0140-production-raw-loader](../specs/0140-production-raw-loader/design.md) · Issue: #140

## Context

[0117](0117-bigquery-holds-one-raw-table-per-endpoint-the-heavy-four-typed.md) stores heavy
endpoints as their declared structures. Something has to turn a document into those columns. AGENTS.md
says ingestion is "fetch-and-save only. It never interprets data", and a load job takes
newline-delimited JSON matching a schema, so a map keyed by player id must be turned into key-value
rows before it, or parsed in BigQuery after it.

The structures live in `dbt/macros/capture_structures.sql`, read by the views and fixtures. On the real
season the only value that needed converting was the league `id`, a number stored as text (spec
0140, C7).

## Decision drivers

- One definition of the structures.
- No second copy of the raw data in BigQuery, and no bill for adding a field.
- The check that runs before anything is sent should see what is sent.
- Nothing CI cannot exercise, as far as possible.

## Considered options

1. **Python reduces at load**, reading the structures from the macro file. Keeps declared fields,
   turns maps into key-value rows, converts a number to text where declared text.
2. **Load whole JSON, parse in dbt incrementally** into typed tables (spec 0140, option E). Python
   stays uninterpreting; SQL is the only parser. Stores both, about 10.7 GB, past the free 10 GiB; adding
   a field bills a full refresh of about 7 GB; BigQuery-only merge models CI never runs.
3. **Load whole JSON, parse by a scheduled `INSERT … SELECT`** outside dbt. As 2, with a second
   home for SQL.
4. **Move the structures to a JSON file** both read. dbt cannot read a project file from a macro,
   so it would need a generated macro and a second generator.

## Decision

Chosen by the owner on 2026-11-02, at the spec's walkthrough: **option 1**.

This reads the rule's intent narrowly and says so: the loader changes a document's shape to a
declared one and assigns no meaning to any value. It decides nothing a model would otherwise decide,
and the landing zone keeps every capture whole. The same step already exists for the three projected
endpoints (ADRs 0061 and 0093). A value that does not fit what is declared, whether a leaf or a
container, stops the load rather than guess.

The file is read by extracting each `{% set structure %}` block by its pair; a test fails if the four
pairs do not parse.

## Consequences

- Good: free to add a field: rebuild one table. One copy stored. Everything but the job itself runs
  in CI, comparing Python's reduction with DuckDB's parse of the same fixture file.
- Good: the privacy check sees exactly what is sent, less for it to walk than a whole document.
- Bad / accepted cost: two readers of a structure, Python here and BigQuery's parse in fixtures, with
  DuckDB's as the third. Tests hold each against another; only BigQuery's fixture parse needs a manual
  run.
- Bad / accepted cost: Python reads a Jinja file as text. A macro rewritten in another form fails the
  test, not silently.
- Follow-ups: AGENTS.md's project-shape line about ingestion names this one exception.
