# 0123. Each run builds BigQuery; DuckDB is built on the laptop when wanted

- Status: proposed
- Date: 2026-11-04
- Spec: [0216-where-the-daily-run-runs](../specs/0216-where-the-daily-run-runs/design.md) · Issue: #216

## Context

Both warehouses build the same models (ADR 0051), and `scripts/compare_bigquery.py` holds them
equal. The dashboard (sub-project 5) will read one of them every day. A full BigQuery build bills
16.16 GB and takes 522 s (spec C12): 485 GB a month if daily, inside the free 1 TiB. A full DuckDB
build of eight seasons fits in 2 GB with the committed profile (C13), which the NAS could give it
beside Dagster, but only just (C15).

## Decision drivers

- The dashboard needs one warehouse current each morning.
- Headroom on the NAS's memory.
- Development keeps a fast local warehouse.

## Considered options

1. **BigQuery daily on the NAS; DuckDB on the laptop, from its copy, when wanted.**
2. **Both daily on the NAS**, DuckDB's file then pulled with the captures.
3. **DuckDB daily on the NAS only**; BigQuery built by hand.

## Decision

Chosen by the owner on 2026-11-05, at the spec's walkthrough: **option 1**, as recommended.

BigQuery is the warehouse a hosted dashboard can read, and building it costs nothing on the NAS
but the build's client (C7). DuckDB's build is what needs memory, and the laptop has 29 GB of it.
Option 2 doubles the run's time and memory for a warehouse nobody reads in the morning. Option 3
leaves the cloud warehouse stale, against sub-project 3's purpose.

## Consequences

- Good: the NAS needs the memory of dbt's client, not of a DuckDB build.
- Good: `front-office load` is not part of the daily run, since DuckDB's manifest is built where
  DuckDB is.
- Bad / accepted cost: a difference between the warehouses shows only when the laptop builds
  DuckDB and compares. That is today's practice.
- Follow-ups: sub-project 5 reads BigQuery.
