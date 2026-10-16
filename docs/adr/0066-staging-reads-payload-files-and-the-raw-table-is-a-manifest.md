# 0066. Staging reads payload files with a declared structure, and the raw table is a manifest with no payloads

- Status: accepted
- Date: 2026-10-14
- Spec: [0150-staging-reads-payload-files](../specs/0150-staging-reads-payload-files/design.md) · Issue: #150

## Context

`raw.api_responses` holds each response whole, one JSON value per row, 8.97 GB of text for eight
seasons (spec 0150, C1). Every staging model re-parses those values, and the same memory
failure has been worked around three times (#143, #149) and is open in #146. Measured for
spec 0150: a smaller row group bounds the load but not the queries (C3, C4); a Parquet
store loads in 0.8 GB but staging over it runs out of memory at one season (C5); read from
the payload files with a declared structure, the four heaviest staging shapes give
today's rows exactly, for eight seasons, in under 1 GB and seconds, no more than for one
season (C6–C9). The memory goes on handing megabyte JSON values to a query, whatever
stores them.

## Decision drivers

- Meet ADR 0065's bar for load, build and test.
- Change no model's rows.
- One mechanism for every endpoint.
- Keep what the raw table guarantees: the key and collision refusal of ADR 0011, an
  append-only record of what was loaded, and ingestion that never interprets.

## Considered options

1. **Read the payload files; the table becomes a manifest** (`raw.captures`: keys and the
   payload's path, no payload), for every endpoint.
2. **The same, for the three heavy endpoints only**; the small ones keep payloads in the
   table.
3. **A smaller row group** (#150 direction 3).
4. **A Parquet store with raw as a view** (#150 direction 1).

Within option 1, the name: `raw.captures`, or `raw.api_responses` without its payload.

## Decision

Chosen by the owner on 2026-10-14: **option 1, for all endpoints, named `raw.captures`**.

The heavy endpoints (`espn/roster`, `espn/matchup_days`, `mlb/boxscore`: 8.84 of the
8.97 GB of payload text) are parsed with a declared structure; the other eight are read as one
whole-document `payload` value per capture, so their models keep their SQL. The loader
lists committed captures through `LandingZone`, refuses key collisions, and inserts keys
and `file_path` (relative to the landing root), without reading any payload. A warehouse
holding the old table is refused and rebuilt from empty, which takes seconds.

Option 2 keeps two mechanisms and a loader that still stores payloads. Options 3 and 4
were measured and fail #146's tests (and, for 4, the build) at 12 GB. `raw.captures` says
what the table now holds; the name `api_responses` stays on BigQuery, where the uploaded
table still holds responses (ADR 0070).

## Consequences

- Good: load in seconds; staging memory flat with seasons; the warehouse no longer
  duplicates the landing zone (8.6 GiB on disk); #146 can be fixed by reading capture views.
- Bad / accepted cost: dbt now depends on the landing zone's layout (ADR 0014) and reads
  files (ADR 0067); a payload that does not parse is found by the model that reads it, not
  at load; nineteen staging models, seven tests and the BigQuery upload change; every
  reader of the old table is renamed.
- Follow-ups: why a JSON extraction costs 0.8 GB in one query shape and 9.8 GB in another
  (C16) is left open; a report to DuckDB is the owner's choice.
