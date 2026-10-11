# 0052. The spike loads raw rows into a native BigQuery table with a `JSON` payload, clustered by source and endpoint

- Status: proposed
- Date: 2026-10-11
- Spec: [0130-bigquery-spike](../specs/0130-bigquery-spike/design.md) · Issue: #130

## Context

On DuckDB, `front-office load` inserts every committed capture into
`raw.api_responses`, one row per response, `payload` typed `JSON`. On 2026-10-11 the real
table holds 5,192 rows and 1.47 GB of payload text: boxscores 944 MB in 4,950 rows,
rosters 441 MB in 182 rows of up to 2.5 MB.

The BigQuery project has no billing account, so it is in the sandbox: DML is refused
(seen by dry run), and so is streaming. Cloud Storage has no sandbox and needs billing.
Load jobs are allowed.

Seen on BigQuery with constants the same day: a JSON path takes no wildcard
(`$.players.*` is refused), so the values of an object keyed by player id, which every
boxscore model reads through `fo_json_values`, can only be reached as `o[k]` for each key
`k`, and that subscript exists for the `JSON` type and not for text. BigQuery bills by
bytes scanned, and whether a `JSON` column is billed whole or by the paths read was not
measured.

`docs/design/01-ingestion-and-staging.md` left "one table per endpoint, or partition by
endpoint" to this migration.

## Decision drivers

- Works in the sandbox, today.
- Both warehouses read the same rows.
- `fo_json_values` must have a BigQuery form.
- Bytes scanned per model should be the endpoint's, not the table's.
- Nothing here should commit the production design, which sub-project 4 owns.

## Considered options

1. **A load job from local newline-delimited JSON into one native table**, `payload` as
   `JSON`, clustered by `source, endpoint`, replaced whole on each run.
2. **The same, with `payload` as `STRING`**, parsed in the macros with `parse_json`.
3. **Captures in Cloud Storage, read through an external table.**
4. **One native table per endpoint.**
5. **Rows inserted by the Python client**, as `load.py` does on DuckDB.

## Decision

Recommended, for the owner to decide: **option 1**, for the spike only.

The rows come from the local warehouse's `raw.api_responses`, so the two builds read the
same rows by construction. Clustering is BigQuery's way of sorting a table's storage by
some columns, so that a query filtering on them reads fewer blocks; every model already
filters on `endpoint`.

Option 2 has no way to write `fo_json_values` without parsing every payload in every
query, and is measured once for one model to know what it would cost (spec 0130, R6.4).
Option 3 needs a billing account, and is the likely production answer once Cloud Run
writes captures to a bucket. Option 4 changes `source('raw', 'api_responses')` in every
staging model on one warehouse only. Option 5 is DML or streaming, both refused.

## Consequences

- Good: no billing account, no bucket, no new service.
- Good: the table has the columns and name the models already read.
- Bad / accepted cost: replace-whole is not the append-only table ADR 0011 describes.
  History is kept locally; the BigQuery table is a copy for the spike.
- Bad / accepted cost: the upload is by hand, and holds whatever the local warehouse
  held when it ran.
- Bad / accepted cost: sandbox tables expire after 60 days.
- Follow-ups: the production loader (bucket or load job, append-only, the collision
  check) is an issue of sub-project 4, written with the bytes this spike measures.
