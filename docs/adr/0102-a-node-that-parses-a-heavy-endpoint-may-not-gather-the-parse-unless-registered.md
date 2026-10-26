# 0102. A node that parses a heavy endpoint may not gather the parse, unless it is registered

- Status: accepted
- Date: 2026-10-25
- Spec: [0156-build-memory-flat-across-seasons](../specs/0156-build-memory-flat-across-seasons/design.md) · Issue: #156

## Context

The nodes whose memory grows from one season to eight all have, in their DuckDB plan, an
operator that gathers its whole input before it emits a row, over a read of a heavy
endpoint's files (spec 0156, C5 to C7):

- `DELIM_JOIN`: DuckDB plans `cross join unnest(...)` this way when a WHERE applies to the
  joined rows, or the list is a struct field (C9); the delim join holds every parsed row.
- `CTE` (read back by `CTE_SCAN`): a CTE, or a repeated subplan, DuckDB materialized; its `common_subplan`
  optimizer does this even for SQL marked `not materialized` (C11).

Nothing in CI can see memory grow: the fixtures are 22 captures. But the plans are the
same on the fixtures as on eight seasons (C13), so CI can see the shape that causes it.

Not every such shape is avoidable at a cost worth paying. The two game-log models read the
newest boxscores through one CTE, for the home and the away side. At four DuckDB threads
(ADR 0100) they grow from 0.5 to 0.75 GB alone, under the 1 GB rung; every shape without
the CTE measured needs more (C15).

## Decision drivers

- A later change that brings back a gathering plan fails CI, not a real-season build
  weeks later.
- A known, measured exception is visible and justified, not silent.
- The check reads what DuckDB does, not a pattern in the SQL text: the causes are
  optimizer decisions (C9, C11).

## Considered options

1. **A plan check with a register of measured exemptions.**
2. **A strict plan check**: every flagged node rewritten.
3. **No CI check**: the real-season ladder at each spec's verification is the check.

## Decision

Chosen by the owner on 2026-10-25: **option 1**.

A gate step runs after the fixture build, as `check_plants.py` does (spec 0174). It finds
every model and test that parses a heavy endpoint's files: one that reaches, through views
alone, a capture view whose source calls `fo_captures` with a declared structure (today
`espn/roster`, `espn/matchup_days`, `mlb/boxscore` and `mlb/schedule`, ADR 0101; read from
the source, so an endpoint with no fixture captures is still covered). It runs
`explain (format json)` on its compiled SQL against `dbt/ci.duckdb`, and fails on a delim join or a materialized CTE whose input reads a heavy endpoint's files,
naming the node, the operator and the endpoint, unless the node is in the register. An
operator's endpoints come from the plan itself: each capture view joins its file read to
a scan of `raw.captures` filtered on `endpoint='…'`. So a gathering operator over a small
endpoint in the same plan (three `stg_espn__scoring_periods_*` tests gather `settings`,
C25) is not a failure.

The register (`dbt/plan_shapes.yml`) lists each exempt node with the operator it
may have, why, and its measured smallest limit alone at four DuckDB threads for 2026 and
for eight seasons, with the date. A node in the register whose plan no longer has the
operator fails the check too, so the register cannot go stale. The register starts with
`stg_mlb__batting_game_logs`, `stg_mlb__pitching_game_logs` and
`stg_mlb__batting_totals_match_team_stats` (the newest-boxscore CTE). An exemption added
later is a decision for the owner, with its measurement.

Option 2 would force the game logs into a shape that costs more than the one it replaces
(C15). Option 3 finds a regression only when someone runs the ladder.

## Consequences

- Good: the cause of memory growth found in this spec is held in CI, and the exceptions
  to it are named, measured and few.
- Bad / accepted cost: a plan check is tied to DuckDB's optimizer: a DuckDB upgrade can
  change a plan, failing the check without a SQL change (or passing it). That is the
  point, since the memory follows the plan, but an upgrade then needs the register looked
  at.
- Bad / accepted cost: the check catches only these two operators. A parse made costly
  another way (a megabyte JSON value through a query, C22) is not caught; the declared
  structures of ADRs 0068 and 0101 are what prevent that.
- Follow-ups: the real-season ladder remains the bar's evidence, recorded on the issue of
  any spec that touches the heavy nodes.
