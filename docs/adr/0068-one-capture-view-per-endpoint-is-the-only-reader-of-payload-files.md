# 0068. One capture view per endpoint is the only reader of payload files

- Status: accepted
- Date: 2026-10-14
- Spec: [0150-staging-reads-payload-files](../specs/0150-staging-reads-payload-files/design.md) · Issue: #150

## Context

dbt unit tests replace a `ref()` or `source()` with fixture rows; they cannot replace a
table function such as `read_json`. Today 24 staging unit tests feed rows to the raw
source (spec 0150, C17). If each staging model read files itself, those tests could not
run. A view over `read_json` works, the glob of ADR 0067 included.

## Decision drivers

- Keep the staging unit tests.
- One place where files are read, behind one dispatched macro (the JSON-macro rule).
- Parse inside each model's own query, as measured.

## Considered options

1. **One view per endpoint** — `stg_raw__<source>_<endpoint>`, one row per committed,
   loaded capture: the manifest's columns plus the declared fields (heavy endpoints) or
   `payload` (the others). Staging models `ref()` it.
2. **`read_json` in each staging model**, declaring only what that model reads.

## Decision

Chosen by the owner on 2026-10-14: **option 1**.

The views are views, so a staging model's query includes the parse, as in the measured
probes (C6–C9). An endpoint's structure is the union of what its models read (rosters:
entries for three models, plus the game lines). Unit tests mock the view; the heavy
views' nested values are written with `format: sql` where dict rows cannot hold them.
Option 2 loses the 24 unit tests.

## Consequences

- Good: unit tests stay; the file read is written once; a model reading a field its
  endpoint's structure lacks fails to compile.
- Bad / accepted cost: three roster models each parse the roster files (2 to 3 s each for
  eight seasons); heavy fixtures are nested and less readable than today's JSON strings.
- Follow-ups: a table of parsed rosters shared by the three models, if the build's
  measurements ever call for it.
