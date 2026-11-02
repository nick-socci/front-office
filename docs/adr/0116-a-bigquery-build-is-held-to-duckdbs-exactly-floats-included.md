# 0116. A BigQuery build is held to DuckDB's exactly, floats included

- Status: proposed
- Date: 2026-10-29
- Spec: [0139-float-order-on-bigquery](../specs/0139-float-order-on-bigquery/design.md) · Issue: #139
- Supersedes: [0053](0053-a-bigquery-build-is-held-to-duckdbs-exactly-except-floats-to-a-tolerance.md)

## Context

ADR 0053 holds a BigQuery build to DuckDB's exactly in every column except floating-point
ones, which are held to a relative 1e-9, because BigQuery could not state the order of a
float aggregate. It left open whether the tolerance would last: "with the measured
differences in hand, decide".

The differences are measured now. Over the whole `bigquery` selector, the largest was a
relative 1.05e-11, and every one was in a sum BigQuery could not order. No column that
is not a float differed (#135). ADR 0115 gives BigQuery the order. With it, the cause of
every difference measured so far is gone. Whether anything else differs is what this
spec's acceptance build finds (spec 0139, R4).

## Decision drivers

- A wrong number, or one computed in a different order, must not pass unseen.
- The check must be one that can pass.
- One rule for both comparisons: DuckDB against BigQuery, and BigQuery against itself.

## Considered options

1. **Exact, floats included.** `compare_bigquery.py` compares every column of every
   relation as a multiset, both ways, as `--bq-against-bq` does now.
2. **Exact, with a register.** Exact by default, but a float column may be listed, with
   its evidence, and held to 1e-9.
3. **Keep the tolerance**, and report how many float values are exactly equal.

## Decision

Chosen by the owner on 2026-10-29, going through the spec's decisions, as recommended:
**option 1**.

If the acceptance build finds a float column that still differs, its cause is traced. It
goes to the owner before anything is excused, and an excuse would be a new decision
against this one. Option 2 builds a place to put such a column before one is known to
exist. Option 3 keeps a check that passes a number computed in a different order, and
that is the thing ADR 0046 forbids.

## Consequences

- Good: one rule for every relation and both comparisons. The README can say that builds
  reproduce to the last digit on both warehouses.
- Good: the tolerance, the join on the declared unique key that floats needed, and the
  per-column report of float differences leave `compare_bigquery.py`.
- Bad / accepted cost: a float that differs for a reason outside ADR 0115 fails the
  comparison, and has to be explained before a BigQuery build passes. That is the
  intent, not a side effect.
- Bad / accepted cost: ADR 0053's note on a category decided within 1e-9 of a tie no
  longer applies, but it was never a protection either: such a category now has to be
  decided alike.
- Follow-ups: none.
