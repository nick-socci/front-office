# 0101. The MLB schedule is read with a declared structure

- Status: accepted
- Date: 2026-10-25
- Spec: [0156-build-memory-flat-across-seasons](../specs/0156-build-memory-flat-across-seasons/design.md) · Issue: #156

## Context

Spec 0150 (R3.2, R3.3) gave three heavy endpoints (rosters, matchup days, boxscores) a
declared structure parsed as each file is read, and left every other endpoint as one
whole-document `payload`, read with `fo_json_*`. Its rabbit holes ruled out declaring
structures for the small endpoints, which were 0.13 GB in all.

The MLB schedule is not small per capture: eight seasons hold 20 captures (2026 alone
holds 4), every one over 1 MB, 66 MB in all (spec 0156, C22). `stg_mlb__games` is a view
over it, so each node that reads `stg_mlb__games` parses every schedule again (C24). With
the build serial on four DuckDB threads (ADR 0100), eight seasons at 1 GB fails only on
two tests that read the schedule (C21), each needing 0.5–0.75 GB for 2026 and 1.5 GB for
eight seasons alone (C22). Declared, the schedule's games read in 0.5 GB for both roots
with the same rows (C24).

## Decision drivers

- The bar of ADR 0065: nothing in the build may need more for eight seasons than for one.
- One mechanism: an endpoint whose captures are large reads them the way the heavy
  endpoints do (ADR 0068).
- No change to what `stg_mlb__games` or any test returns.

## Considered options

1. **Declare the schedule's structure** in `stg_raw__mlb_schedule`: `dates[].games[]`,
   each game kept as JSON.
2. **Materialize `stg_mlb__games` as a table**, so its readers parse the schedule once.
3. **Both.**

## Decision

Chosen by the owner on 2026-10-25: **option 1**. `stg_raw__mlb_schedule` declares
`{"dates": [{"games": ["JSON"]}]}` and gives no `payload`. A structure stops where its
readers already read element by element (spec 0150, *Amendments*), so `stg_mlb__games`
and `stg_mlb__games_prefers_played_over_unplayed` keep their `fo_json_*` reads of each
game, from a shorter path. Any other field a reader of the schedule takes is added to the
structure. The schedule becomes a heavy endpoint for the plan check of this spec.

Option 2 fixes the readers of `stg_mlb__games` but not
`stg_mlb__games_prefers_played_over_unplayed`, which reads the capture view directly to
compare staging against it. Option 3 changes `stg_mlb__games`'s materialization on
BigQuery too, for no further gain measured.

## Consequences

- Good: the schedule is parsed as it is read, as the heavy endpoints are; a reader no
  longer passes a megabyte JSON value through a query.
- Good: every reader of `stg_mlb__games` gets the cheaper parse, without a new table.
- Bad / accepted cost: spec 0150's rabbit hole is reversed for one endpoint, and the
  structure must be kept in step with what the schedule's readers take (a field not
  declared fails the model when it compiles, ADR 0068).
- Follow-ups: none planned. Another small endpoint whose captures grow past a megabyte
  gets the same treatment, by its own decision.
