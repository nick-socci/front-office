# 0113. A JSON fixture value stays JSON text, and BigQuery parses it

- Status: proposed
- Date: 2026-10-29
- Spec: [0138-unit-tests-on-bigquery](../specs/0138-unit-tests-on-bigquery/design.md) · Issue: #138

## Context

Dict fixtures give JSON columns (`partitions`, the small capture views' `payload`) as
JSON text in a YAML string. dbt casts each fixture value with its `safe_cast` macro. On
DuckDB that is `cast('…' as JSON)`, which works. dbt-bigquery's `safe_cast` takes a YAML
*mapping* for a JSON column, but casts a *string* with `cast(… as JSON)`, which BigQuery
refuses (spec 0138, C9). Eight tests fail on that alone (C4).

A project macro `bigquery__safe_cast` replaces the adapter's in dbt's fixture SQL (C10).
Only fixture SQL calls `safe_cast` here (C17).

## Decision drivers

- No rewrite of fixtures that are right today.
- A fixture's JSON is exactly the text it means, with no YAML reinterpretation.
- Quotes, apostrophes and backslashes survive on both warehouses.

## Considered options

1. **JSON stays text.** A project `bigquery__safe_cast` sends a string given to a JSON
   column to `parse_json`, building the string literal itself so that backslashes
   survive. Everything else goes to the adapter's form.
2. **JSON becomes YAML mappings.** Every JSON value is rewritten as a mapping, which
   dbt-bigquery already takes. A project `duckdb__safe_cast` writes it as `json('…')`,
   because DuckDB would otherwise read Python's text of the dict as a struct literal.

## Decision

Chosen by the owner on 2026-10-29, as recommended: **option 1**. With it, the eight tests
pass on BigQuery unchanged, and quotes, apostrophes and backslashes come back exactly
(C10, C19).

Option 2 also works on both warehouses (C14). It needs every JSON value in the dict
fixtures rewritten, and YAML would then interpret the values: an unquoted `on` or `yes`
becomes `true` (C15). Text is what the API sends and what lands.

## Consequences

- Good: the dict fixtures are not touched.
- Good: dbt's own literal leaves backslashes for BigQuery to unescape, which breaks JSON
  holding `\"` (C11). The override builds the literal itself, and a new unit test holds
  that (R4.2).
- Bad / accepted cost: the project overrides a dbt adapter macro. A dbt-bigquery release
  that renamed `bigquery__safe_cast`, or moved it out of the `dbt` namespace, would show
  up only in the by-hand BigQuery run (ADR 0110).
