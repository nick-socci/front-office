# 0067. A model reads committed captures by a glob of committed names, inner-joined to the manifest

- Status: accepted
- Date: 2026-10-14
- Spec: [0150-staging-reads-payload-files](../specs/0150-staging-reads-payload-files/design.md) · Issue: #150

## Context

ADR 0066 has dbt read payload files. AGENTS.md says the landing zone is read only through
`LandingZone` and never globbed by hand, because a capture is written in
`fetched_at=<stamp>.tmp-<pid>/` (its `payload.json` first) and published by one rename
(ADR 0014): a careless glob reads half-written files. DuckDB's `read_json` takes a
constant file list or a glob. Measured (spec 0150): a file list passed by a pre-hook
variable works for a table and not for a view, and tests cannot have pre-hooks (C14); a
filter on the file name does not stop DuckDB opening a half-written file, a filter on a
hive column does but fails where depth varies (`espn/transactions`) (C12); the glob
`**/fetched_at=*Z/payload.json` matches all 27,417 committed captures, no temporary
directory, at any depth (C11); a glob with no match is an error (C13).

## Decision drivers

- A half-written capture is never opened.
- The record written through `LandingZone` stays the authority on what is a capture.
- Plain SQL that works in tables, views and tests.

## Considered options

1. **Glob plus manifest** — read the endpoint's committed captures by a glob that only
   matches committed names, and inner-join to `raw.captures` on `file_path`.
2. **Manifest plus variable** — a pre-hook sets a DuckDB variable to the manifest's paths,
   and the model reads exactly those.
3. **List at compile time** — a macro writes the manifest's paths into the SQL.

## Decision

Chosen by the owner on 2026-10-14: **option 1**.

Option 1 as put to the owner filtered on the `fetched_at` path value. Two measurements
taken while writing the spec narrowed the mechanism without changing the choice: the
hive filter fails on mixed depths, and a file-name filter opens the file anyway (C12).
The glob pattern itself excludes temporary directories, because a published stamp ends in
`Z` (`cli.utc_stamp`) and a temporary name ends in a process id. The pattern is
`<root>/<source>/<endpoint>/**/fetched_at=*Z/payload.json`, and the inner join to
`raw.captures` drops anything the loader has not recorded. An endpoint with no match
gives an empty relation, checked through `glob()` before reading (C13).

Option 2 cannot serve views or tests and hides state in the session. Option 3 puts
about 2 MB of paths into each boxscore model's SQL and makes compiling depend on a loaded
warehouse.

## Consequences

- Good: plain SQL everywhere; a half-written capture is never opened; the manifest stays
  the authority; AGENTS.md's rule is amended to name exactly this reader.
- Bad / accepted cost: every committed capture of the endpoint is parsed, superseded
  snapshots included (boxscores 24,385 for 19,438 games; rosters 1,471 for 1,469), and the
  newest is then chosen on the manifest's columns and kept by a semi-join, never by
  ranking parsed rows (C19); the join decides which rows count, not which files are
  opened, so a malformed payload in a published-looking directory fails the build even
  if the manifest does not list it, until `front-office repair` quarantines it; the
  stamp's trailing `Z` becomes part of the contract with ADR 0014, and the loader enforces
  it.
- Follow-ups: if the stamp format ever changes, this glob changes with it; the test of
  R2.1 holds the two together.
