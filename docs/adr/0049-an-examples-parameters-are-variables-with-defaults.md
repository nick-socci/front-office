# 0049. An example's parameters are DuckDB variables that default to the committed values

- Status: proposed
- Date: 2026-10-10
- Spec: [0117-examples-return-stated-rows](../specs/0117-examples-return-stated-rows/design.md) · Issue: #117

## Context

`roster_day_query.sql` names a league, a team and a date in a `params` block: `'73677'`,
`6`, `2026-07-02`. They are the real season's. The fixture warehouse holds league
`111111` on three days of April, so in CI the example returns nothing, and no check of
what it returns (ADR 0048) can be made until it is asked about a team-day the fixtures
hold.

Checked on 2026-10-10 with DuckDB 1.5.5 through the Python package: `getvariable` of a
name never set is NULL, so `coalesce(getvariable('team_id'), 6)` is 6 until a session
sets `team_id`. Rewritten this way, the example returns on the real season the same 18
rows as the committed file, compared row for row, and on the fixtures 18 rows for team
11 on 2026-04-29. Variables arrived in DuckDB 1.1, which `pyproject.toml` already
requires. The command-line client was not available to check.

## Decision drivers

- The file is for a reader to pipe into DuckDB as it is; it must keep returning the real
  season's answer with nothing set.
- CI should run the text that is committed.
- The fixtures are shared by every model's tests; one example should not reshape them.

## Considered options

1. **Variables with defaults**: each parameter is `coalesce(getvariable('<name>'),
   <committed value>)`; the gate sets the variables it states for the example.
2. **The gate rewrites the `params` block** with fixture values before running the file.
3. **The fixtures gain the real league's team-day**, so the committed values match.
4. **The committed values become the fixtures'.**

## Decision

Recommended, for the owner to decide: **option 1**.

Option 2 tests a query nobody committed and depends on a text pattern surviving every
edit to the block. Option 3 is the only one that tests the committed values themselves,
and costs a new fixture day, the real league's id as a fixture league and every recorded
fixture count. Option 4 makes the README's first query return nothing on a real league.

## Consequences

- Good: the fixtures do not change.
- Good: a reader can ask about another team or day without editing the file.
- Bad / accepted cost: what CI runs is the committed query under other parameters. That
  the defaults are still league `73677`, team 6, 2026-07-02 is held only by a test that
  reads the file's text; that they return the right rows is checked on the real season
  when the file changes.
- Bad / accepted cost: the file needs DuckDB 1.1 or later.
- Follow-ups: the command-line client's behaviour is confirmed in the build's first
  task; if it differs, this decision is revisited before anything is built.
