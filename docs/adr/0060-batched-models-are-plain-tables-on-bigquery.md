# 0060. A batched model is a plain table on BigQuery

- Status: superseded by [0069](0069-staging-models-are-built-whole-not-a-season-at-a-time.md)
- Date: 2026-10-12
- Spec: [0143-staging-by-season](../specs/0143-staging-by-season/design.md) · Issue: #143

## Context

ADR 0058 batches five staging models by season because DuckDB runs out of memory. Since
#130, thirty models are written once and build on BigQuery too (ADR 0051), these five
among them. BigQuery built them in one piece without trouble, and it bills a query for
the whole `JSON` payload column of the endpoint it reads: 827 MB for each boxscore
model (spec 0143, C12). A batch is a query. Nine seasons of batches would bill a
boxscore model nine times.

## Decision drivers

- A model is written once (ADR 0051).
- Bytes billed.
- The column set of a model should not depend on the warehouse.

## Considered options

1. **A table on BigQuery, microbatch on DuckDB**: the materialization is chosen by the
   target in the model's config; the SQL and the columns are the same.
2. **Microbatch on both**, with the partitioned table BigQuery's form of it needs.
3. **A separate model file for BigQuery.**

## Decision

Chosen by the owner on 2026-10-12, going through the spec's decisions: **option 1**. `materialized` is `incremental` with the microbatch strategy
when the target is DuckDB and `table` otherwise. `season_start` is a column on both.

Option 2 multiplies what a build bills by the number of seasons for a limit BigQuery
does not have. Option 3 is what ADR 0051 exists to prevent.

## Consequences

- Good: a BigQuery build bills what it bills today.
- Good: one file a model, one column set.
- Bad / accepted cost: the two warehouses build these five by different mechanisms, so
  the comparison of spec 0130 is what shows they agree, not the config.
- Bad / accepted cost: a config that reads the target is one more thing a reader of a
  model must follow.
