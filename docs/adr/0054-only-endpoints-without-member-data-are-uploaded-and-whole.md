# 0054. Only endpoints without league members' data are uploaded, and their captures whole

- Status: accepted
- Date: 2026-10-11
- Spec: [0130-bigquery-spike](../specs/0130-bigquery-spike/design.md) · Issue: #130

## Context

The repository is public and the ESPN league is private. Rule 2 keeps members' data out
of anything committed; the raw captures, which do hold it, have so far lived only on the
owner's machine and the NAS. Building on BigQuery means some of them leave the house for
the first time, into a project private to the owner's Google account.

Counted on 2026-10-11 with the patterns of `front_office/privacy.py`, over the three
latest captures of each endpoint:

| Endpoint | Member keys | Account GUIDs |
|---|---|---|
| `espn/teams` | `members`, `owners`, `primaryOwner`, `displayName`, `firstName`, `lastName` | 652 |
| `espn/transactions` | `author` (15,303) | 49,942 |
| `espn/roster`, `espn/matchups` | `firstName`, `lastName`, only under `playerPoolEntry.player`: ballplayers | 0 |
| `espn/settings`, `espn/pro_schedule` | none | 0 |
| `mlb/*`, `idmap/*` | none (`mlb/players` names ballplayers) | not ESPN |

The `settings` payload holds the league's name. The slice of spec 0130 reads seven
endpoints and neither `teams` nor `transactions`.

## Decision drivers

- Members did not agree to their names or account ids being put anywhere.
- The upload should be checked by the same patterns that guard commits, not by a second
  list.
- The models should read on BigQuery what they read on DuckDB.
- The spike should not have to design the answer for the two hard endpoints.

## Considered options

1. **Upload whole captures of an allowlist of endpoints that carry no member data**, and
   check every row against the privacy patterns before anything is sent.
2. **Upload everything.** The project is private.
3. **Upload a projection**: only the fields the staging models read, for every endpoint.
4. **Upload nothing raw**: build staging on DuckDB and upload the staging tables.

## Decision

Chosen by the owner on 2026-10-11, going through the spec's decisions: **option 1**.

The spike's loader holds an allowlist of seven `(source, endpoint)` pairs. Before
writing a file it walks every row: a GUID anywhere in an ESPN row, or a forbidden key
in any row, stops the upload and names the endpoint and path, never the value. The one
exception is `firstName` and `lastName` directly in a `playerPoolEntry.player` object,
which name a ballplayer. MLB rows are not checked for GUIDs, as `privacy.py` is not:
`gameGuid` is a public game id. League and team names are not member data
by rule 2's list, and do go up: the `settings` payload has the league's name, and the
BigQuery build runs with `anonymize: false` so that it can be compared with DuckDB's.

Option 2 is the simplest and may be what the owner wants in the end, but it is a
decision about other people's data that a spike should not make by default. Option 3 is
the fixture approach applied to the real season: it means a second definition of every
payload's wanted fields, and the models would read different JSON on each warehouse.
Option 4 leaves the JSON macros, the largest unknown, untested.

## Consequences

- Good: nothing that names a member or an account leaves the machine.
- Good: one definition of member data, used for commits, fixtures and uploads.
- Bad / accepted cost: `stg_espn__teams`, `stg_espn__transactions` and every model
  downstream of them, all outside the slice, cannot be built on BigQuery until this is
  decided for those two endpoints.
- Bad / accepted cost: the league's name, and fantasy team ids, are in a cloud project.
- Follow-ups: an issue in the milestone decides `teams` and `transactions`: upload them
  whole, or strip the member keys and GUIDs at upload. It is the owner's decision and
  blocks the full migration, not the spike.
