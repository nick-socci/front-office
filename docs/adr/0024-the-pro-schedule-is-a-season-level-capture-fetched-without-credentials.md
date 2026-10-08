# 0024. The pro schedule is a season-level ESPN capture, fetched without credentials

- Status: proposed
- Date: 2026-10-07
- Spec: [0073-espn-pro-schedule](../specs/0073-espn-pro-schedule/design.md) · Issue: #73

## Context

Every ESPN capture so far belongs to a league: it is filed under
`season=<year>/league_id=<id>`, fetched with the account's session cookies, and
`fo_espn_latest`, the audit and the tenant-isolation check all assume that shape. The pro
schedule belongs to ESPN's game for a season. The request names no league and needs no
login, and the response has teams and games and no member data.

## Decision drivers

- Credentials go only where they are needed (AGENTS.md rule 3).
- One schedule per season, however many leagues are loaded.
- A past season's schedule should be fetchable with no league at all.
- As little new machinery as possible.

## Considered options

1. **Source `espn`, endpoint `pro_schedule`, partition `season` only**, fetched by a
   client with no cookies.
2. **File it under each league**, `season/league_id`, fetched in the league run.
3. **A new source**, for ESPN's public game data.

## Decision

Chosen: **option 1**, by the owner on 2026-10-07.

The capture is `espn/pro_schedule/season=<year>/fetched_at=<stamp>/`. `backfill espn`
lands it first, with a client that carries no cookies; `--only pro-schedule` lands it
alone and reads no credentials. It is a snapshot: every run lands one.

Option 2 stores the same 850 KB once per league, sends session cookies to a request that
does not need them, and makes one league's copy disagree with another's by fetch time.
Option 3 is cleaner on paper but adds a source to the loader's vocabulary, the audit and
the fixtures for one endpoint of the same API.

## Consequences

- Good: no credential reaches a request that does not need it.
- Good: a past season's schedule needs no league and no `.env`.
- Bad / accepted cost: the first ESPN folder without a `league_id` level. The
  tenant-isolation check and the audit learn that shape; `fo_espn_latest` already
  handles it, grouping a season's captures under a null league.
- Bad / accepted cost: about 850 KB on every `backfill espn`, 150 MB over a season of
  daily runs.
- Bad / accepted cost: the ESPN run now makes one request outside the authenticated
  client, so a failure there stops the run before the league data is fetched.
