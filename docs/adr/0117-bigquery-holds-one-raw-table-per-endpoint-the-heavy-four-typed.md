# 0117. BigQuery holds one raw table per endpoint, the heavy four typed, and `raw.captures` is the manifest on both warehouses

- Status: proposed
- Date: 2026-11-02
- Spec: [0140-production-raw-loader](../specs/0140-production-raw-loader/design.md) · Issue: #140
- Supersedes: [0052](0052-the-spike-loads-raw-rows-into-a-native-bigquery-table-with-a-json-payload.md), [0114](0114-a-unit-test-names-the-manifest-through-the-target.md)
- Amends: [0054](0054-only-endpoints-without-member-data-are-uploaded-and-whole.md), [0070](0070-bigquery-reads-its-uploaded-table-through-the-same-capture-views.md)

## Context

A full BigQuery build bills 56.07 GB, of which 47.83 GB is nodes reading `raw.api_responses`
(spec 0140, C1, C3). At one build a day that is 1.53 TiB a month, 3.31 USD over the free terabyte
of a 5 USD budget (C2). Two causes: a `JSON` column bills whole however little is read, so a
boxscore model bills 6.98 GB and takes up to 1,031 s (C4); and clustering reads whole blocks, so a
test of the 4 MB id map bills 0.32 GB of its neighbours (C5).

Run on the real season with each model's compiled SQL, and compared with the populated tables,
typed columns give identical rows at 0.29 to 0.44 GB and 5 to 6 s for the boxscore models, and a
table of its own bills the id map 0.010 GB (C6, C8).

## Decision drivers

- A daily build inside the free terabyte; the owner treats cost as a deciding criterion.
- No model's rows or SQL change (ADR 0051).
- One definition of what a model reads.
- As little BigQuery-only machinery as possible, since CI never runs it.

## Considered options

Estimates use C9's method. Each is 11 endpoints' worth of the same data.

1. **One table per endpoint, the heavy four typed** by their declared structure, the rest whole
   JSON: ~14.5 GB a build, 0.39 TiB a month daily, free; ~2.3 GB stored.
2. **One table as today, appended to:** 56.07 GB, 3.31 USD a month daily; 8.44 GB stored.
3. **One table, payloads projected to the structures:** ~43 GB, ~1.05 USD a month; boxscore
   models still up to 855 s (C11).
4. **One table per endpoint, whole JSON:** ~31 GB, free daily but near the limit; still parses.
5. **JSON table plus dbt incremental typed tables:** ~15 GB and each new capture's parse; ~10.7 GB
   stored; BigQuery-only merge models.
6. **A bucket and an external table:** 3.4 times the native table (C13).

## Decision

Chosen by the owner on 2026-11-02, at the spec's walkthrough: **option 1**.

Tables are `raw.<source>_<endpoint>`. `mlb/boxscore`, `espn/roster`, `espn/matchup_days` and
`mlb/schedule` hold their declared structures' fields as columns. The other seven hold `payload`
as `JSON`. `raw.captures` holds the manifest, with DuckDB's columns and meaning, so
`fo_capture_keys` and the unit tests' manifest input stop depending on the warehouse.
`raw.api_responses` goes.

Option 2 leaves the cost. Options 3 and 4 each remove one of the two causes. Option 5 is
[0118](0118-the-loader-reduces-a-heavy-capture-to-its-declared-structure.md)'s to weigh. Option 6
was measured.

## Consequences

- Good: an estimated 14.45 GB a build, 76 in the free terabyte; heavy staging in seconds; storage
  back inside the free 10 GiB once the old table goes.
- Good: the manifest has one name; 0114's conditional input goes.
- Good: what 0070 accepted as a cost, the two warehouses' views reading differently, narrows: both
  now read a declared structure.
- Bad / accepted cost: 0054's "whole" no longer holds for `espn/roster` and `mlb/*` heavy endpoints:
  what goes up is the declared fields. A field not declared is not on BigQuery until a rebuild.
- Bad / accepted cost: a table name per endpoint in the sources, and a new endpoint adds a table.
- Follow-ups: the whole-build figure is an estimate, held at no more than 20 GB by spec 0140.
