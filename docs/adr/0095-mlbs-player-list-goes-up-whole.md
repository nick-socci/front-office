# 0095. MLB's player list goes up whole, its people's own names allowed

- Status: accepted
- Date: 2026-10-22
- Spec: [0136-member-endpoints-to-bigquery](../specs/0136-member-endpoints-to-bigquery/design.md) · Issue: #136
- Amends: [0054](0054-only-endpoints-without-member-data-are-uploaded-and-whole.md)

## Context

`mlb/players` was outside the spike's slice, so ADR 0054 left it off the upload.
`stg_mlb__players` reads it, and `dim_players` reads that, so neither can build on BigQuery
without it. The list is public MLB data and holds no ESPN data. Every person in it carries
`firstName` and `lastName` (spec 0136, C10). 0054's check stops on those two keys in any
row, except directly in an ESPN `playerPoolEntry.player` object, where they name a
ballplayer. Uploaded as it stands, the player list would stop the upload on every person.

The 9 captures hold 15.10 MB. A projection of the 7 fields `stg_mlb__players` reads, which is
`PLAYER_LIST_FIELDS`, the fixture's list, holds 3.92 MB (C11).

## Decision drivers

- The check of a commit, a fixture and an upload is one definition of member data
  (`front_office/privacy.py`). An exception to it must be as narrow as the case it serves.
- Models read the same JSON on both warehouses (ADR 0051), with as few second definitions of
  a payload as possible (ADR 0054's reason for uploading whole).
- Bytes billed: a `JSON` column is billed whole (spec 0130, R6.4).

## Considered options

1. **Whole, with a second ballplayer exception.** `firstName` and `lastName` are allowed
   directly in an object of `$.people[]` of an `mlb/players` row, as they are in
   `playerPoolEntry.player`.
2. **A projection of the fields `stg_mlb__players` reads**, built from `PLAYER_LIST_FIELDS`
   as ADR 0093 builds teams and transactions.
3. **No key check on MLB rows at all**, as `privacy.py` and the pre-commit guard check only
   ESPN fixtures.

## Decision

Chosen by the owner on 2026-10-22, at the spec's walkthrough: **option 1**.

The player list is public, and 0054 uploads public endpoints whole so that both warehouses
read the same document. The exception names one endpoint, one place in it and two keys.
Every other forbidden key in an `mlb/players` row still stops the upload, and so does every
forbidden key in any other MLB row.

Option 2 saves about 11 MB per build, against a build of 5.35 GB (spec 0130, R6.1). It also
makes `stg_mlb__players` the third model whose BigQuery input is a second definition. Option
3 is the widest exception: it drops the key check from every MLB endpoint, boxscores and
schedules included, so an MLB endpoint added later would be guarded only by the allowlist.

## Consequences

- Good: `stg_mlb__players` and `dim_players` read the same document on both warehouses.
- Good: the exception is shaped like the one already there, so the check reads one rule with
  two places.
- Bad / accepted cost: a 15 MB JSON column goes up and is billed whole by any query of it.
- Follow-ups: none.
