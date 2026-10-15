# 0070. BigQuery reads its uploaded table through the same capture views, and the upload reads the landing zone

- Status: proposed; amends [0052](0052-the-spike-loads-raw-rows-into-a-native-bigquery-table-with-a-json-payload.md)
- Date: 2026-10-14
- Spec: [0150-staging-reads-payload-files](../specs/0150-staging-reads-payload-files/design.md) · Issue: #150

## Context

ADR 0051 writes each model once for both warehouses. BigQuery has no local landing zone
to read. The slice's upload (ADR 0052, `scripts/spike_load_bigquery.py`) copies rows from
the DuckDB warehouse's `raw.api_responses`, which ADR 0066 removes. The production
BigQuery loader is #140's: the spike's measurements point to a bucket and a native table.

## Decision drivers

- One model definition for both warehouses.
- BigQuery's rows and bytes billed unchanged.
- Do not design #140 here.

## Considered options

1. **Dispatch, BigQuery as today** — each capture view is a dispatched macro: on DuckDB it
   reads files joined to `raw.captures`, on BigQuery it reads the uploaded
   `raw.api_responses` and parses with the existing `bigquery__` macros. The upload reads
   keys from `raw.captures` and payloads through `LandingZone`.
2. **Redesign BigQuery's raw layer now** — land captures in a bucket, with typed tables.

## Decision

Chosen by the owner on 2026-10-14: **option 1**. This amends ADR 0052 only in where the
upload's rows come from: the landing zone through `LandingZone`, not the local table. The
privacy check (ADR 0054) and the projections (ADR 0061) are unchanged, and so is the
table BigQuery holds. Two declared structures hold maps (a boxscore side's players, a
game line's stats), which BigQuery has no type for: `bigquery__fo_json_parse` gains a map
leaf, given as an array of key–value structs, and models read maps only through
dispatched `fo_map_values` and `fo_map_entries`.

Option 2 answers #140 inside this spec and needs decisions about buckets, load jobs and
billing that #140 exists to make.

## Consequences

- Good: BigQuery builds and bills as before; the slice comparison still holds the two
  warehouses together.
- Bad / accepted cost: the two warehouses' capture views read differently (files on
  DuckDB, a JSON column on BigQuery), so only the slice comparison shows they agree.
- Follow-ups: #140 designs the production loader; it can give BigQuery typed tables, and
  the capture views' BigQuery variant then changes in one place.
