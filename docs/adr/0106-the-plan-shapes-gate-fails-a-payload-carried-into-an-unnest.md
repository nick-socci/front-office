# 0106. The plan-shapes gate fails a payload carried into an unnest, with no exemption

- Status: proposed
- Date: 2026-10-28
- Spec: [0134-payload-beside-an-unnest](../specs/0134-payload-beside-an-unnest/design.md) · Issue: #134

## Context

AGENTS.md rule 1 says to project `payload` away before any `unnest`: an unnest repeats every
other column of its input once per element, and a payload carried beside the unnest of
ESPN's rosters exhausted 24 GB. Two other AGENTS.md rules are held by a test in the gates
(JSON access, #79; ordered float aggregates, ADR 0046). Rule 1 is held only by comments.

Since #134 was filed, the heavy endpoints stopped having a `payload` at all (spec 0150, ADR
0101): their capture views parse a declared structure, and ADR 0102 holds their plans. Seven
endpoints still expose a `payload` column, from 6 KB (settings) to 4.3 MB (the id map) on the
real season (spec 0134, C4). Every unnest in the project goes through `fo_unnest` or
`fo_unnest_pair` in a FROM clause (ADR 0051), and none carries a payload today (C1, C5).

The memory goes where DuckDB's plan sends it. In the plan, every shape rule 1 forbids looks
the same: an operator that gives one row per list element is fed a projection that holds
the column `payload`. That operator is an `UNNEST`, the `unnest` table function, or a
`CROSS_PRODUCT` or join with an unnest somewhere under one side (C6, C7, C11, C12). The
header form never does this.

## Decision drivers

- A model that carries a payload into an unnest fails CI, not a real-season build.
- The check judges what DuckDB carries, not a guess at SQL structure through Jinja: ADR
  0102 chose the plan for the same kind of question.
- There is no excuse for carrying a payload, so there is no way to excuse it.

## Considered options

1. **A plan check in `scripts/check_plan_shapes.py`, no exemption.** Readers of a payload
   capture view are explained; any unnest fed a `payload` column fails.
2. **A text test in pytest**, like the JSON and ordered-aggregate rules: find the SELECT
   around each `fo_unnest`, and fail if it names `payload`.
3. **Both.**
4. **Option 1 with a register entry**: a `plan_shapes.yml` operator `unnest_payload`, with a
   measured size, so a small payload could be carried by exception.

## Decision

Chosen by the owner on 2026-10-28, as recommended: **option 1**.

The gate step `check_plan_shapes.py` finds every model and test that reaches a payload
capture view (one whose source calls `fo_captures` with two arguments) through views and
ephemerals, as it finds heavy readers. It explains each one. It fails when an `UNNEST`
operator or `unnest` table function is fed a column named `payload`. It also fails when a
cross product or a join that repeats rows has an unnest anywhere under one side and
`payload` on the other. The failure names the node and the endpoints it reads. Three probe
queries that do carry a payload must be flagged on every run. It registers the lineup solver from `fo_duckdb_functions` on its
connection, so the one model that calls it is explained too.

No register entry can exempt a carry (option 4 not chosen). The header form costs nothing
and changes no rows: #130 and #135 rewrote `stg_espn__scoring_categories` and
`stg_espn__teams` that way. If a case for an exemption appears, a new ADR adds one.

Option 2 has to find a SELECT's bounds through Jinja without a parser. It cannot see a
`select *` or SQL a macro builds from pieces, and it duplicates a mechanism ADR 0102 already
chose. What it has that option 1 lacks: it fails in seconds with a line number, and sees
an endpoint with no fixture capture. The gate makes up for the second by failing when a
payload endpoint has no capture. Option 3 is two implementations of one rule that agree on
every site today (C1, C5).

## Consequences

- Good: rule 1 is held in CI, by the same step that holds the heavy endpoints' plans.
- Good: a DuckDB upgrade that changes the plan format cannot quietly switch the check off.
  The gate checks three known carries on every run, and fails if any is not caught.
- Bad / accepted cost: the check keys on the column name `payload`, the capture views' name
  for it (ADR 0068). `payload as body` carried beside an unnest passes (C6). A large column
  that is not a payload (a parsed list carried beside its own unnest) is not caught either.
- Bad / accepted cost: it runs after the fixture build, minutes into the gates, not in
  pytest.
- Follow-ups: none. 21 nodes have a delim join over a payload endpoint (C9). ADR 0102
  already decided that is not a failure on a small endpoint, and this decision does not
  change that.
