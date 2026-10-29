# 0112. A fixture calls a project macro inside a raw block

- Status: accepted
- Date: 2026-10-29
- Spec: [0138-unit-tests-on-bigquery](../specs/0138-unit-tests-on-bigquery/design.md) · Issue: #138

## Context

A portable fixture needs project macros: `fo_capture_rows` (ADR 0111), `fo_type_float`,
`fo_int_series`. dbt renders a unit test's `rows` when it parses the YAML, and the
project's macros do not exist yet at that point. So `{{ fo_type_float() }}` written in
`rows` fails as undefined (spec 0138, C6). Two ways around this were tried, and both
work on both warehouses:

- In `{% raw %}…{% endraw %}`, the call survives the parse as text. It is rendered when
  the fixture is compiled, with the target's dispatched form (C6).
- A SQL file under `dbt/tests/fixtures/`, given with `fixture: <name>`, is compiled with
  the project's macros and needs no `{% raw %}` (C7).

## Decision drivers

- A test should read in one place: its description, its inputs, its expected rows.
- No new kind of file for the gates to lint, scan and guard.

## Considered options

1. **Inline, in `{% raw %}`.** The macro call is written in the test's YAML, wrapped.
2. **Fixture files.** The SQL moves to `dbt/tests/fixtures/<name>.sql`, and the YAML
   names it.

## Decision

Chosen by the owner on 2026-10-29, as recommended: **option 1**.

Every unit test today keeps its inputs beside its description. Option 2 would split 40
tests across two files each. It would also add a directory that `sqlfluff lint dbt/tests`
reads as SQL to template, and that the portable rule and the privacy guard would have to
learn. The cost of option 1 is one unusual wrapper, explained once in AGENTS.md.

## Consequences

- Good: each test stays in one place.
- Bad / accepted cost: `{% raw %}` reads oddly to someone who has not seen why. AGENTS.md
  says why.
- Bad / accepted cost: this rests on dbt rendering `rows` twice, at parse and at compile.
  If a dbt release stopped the second render, the calls would reach the warehouse as
  text, and every such test would fail in CI at once.
