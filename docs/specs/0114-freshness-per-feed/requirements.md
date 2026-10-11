# Source freshness is one age per feed — requirements

Issue: #114 · Tier: M · Status: draft

## Problem

`raw.api_responses` has one freshness check, and the table holds three feeds: `mlb`,
`espn` and `idmap`. `dbt source freshness` reports the age of the table's newest row, so
a feed that has stopped is hidden by one that has not. On the real warehouse on
2026-10-10 the newest captures were:

| feed | newest capture (UTC) |
|---|---|
| mlb | 2026-10-09T19:42:27 |
| espn | 2026-10-08T16:38:28 |
| idmap | 2026-09-26T17:36:54 |

The table's age was a day; the id map's was fourteen, and nothing would have said so.

Grounding found the same fault one level down. The `mlb` feed's newest capture is a
player list landed alone on 10-09; its newest schedule, which every full run lands, is
from 10-08. And a full `espn` run lands ESPN's public pro schedule before anything that
needs the login, so when the login expires, which is the likeliest way for that feed to
stop, the feed's newest capture stays fresh. An age per feed is not enough: it has to be
the age of a capture that only a run of the feed's league or season data produces.

And one level further, found in the second design review. Neither marker says which
season it belongs to, and past seasons are fetched too: the backfill of 2018 to 2025 for
#57 landed a schedule and a settings capture for each. On the real warehouse the newest
`mlb` schedule (2026-10-08T16:38:27) and the newest `espn` settings (2026-10-08T16:38:28)
are the 2018 season's. The 2026 season's own are a day older (10-07T22:11:16 and
10-07T17:16:57). A past-season backfill would make a stalled feed look fresh.

Freshness is dormant today (spec 0013, R4.3) and wakes with the 2027 daily schedule. This
spec settles its shape before then; it does not wake it.

## Goals

- `dbt source freshness` reports one age for each feed, so a stalled feed is seen
  whatever the others are doing.
- A feed's age is the age of its last run for the season being played, not of whatever
  it landed last: a capture of another endpoint, an unauthenticated call or an earlier
  season does not count.
- Each feed has thresholds that fit how often it is fetched, the id map's among them.
- A feed that has committed fixtures cannot be left without a freshness declaration
  unnoticed.
- What freshness answers, and what nothing yet answers, is written down.

## No-gos

- Freshness is not woken. No gate, no CI job and no schedule runs `dbt source freshness`
  (spec 0013, R4.3 stands): the fixtures are stale by design.
- No change to `raw.api_responses`, to the loader, or to any model's `source()` call.
  Every model keeps reading `source('raw', 'api_responses')`.
- No freshness per endpoint, and no check that a run landed every endpoint it should
  have. Named as a remaining limit (see *Rabbit holes*).
- No freshness per league. Named as a limit, with the alternative that removes it; the
  owner accepted the limit on 2026-10-10 (design, *Settled by the owner*).
- No change to `front-office audit`.
- No daily schedule, and no alerting.

## Rabbit holes

- **Per-endpoint ages.** Some endpoints are fetched only when there is something to
  fetch: a day with no games lands no boxscore, and an endpoint age would warn on every
  off day. → One capture per feed is named as the mark of a run (R1.1), and freshness is
  the age of that. It answers "did this feed's run start and reach its first league or
  season call".
- **"Did the run land everything."** Nothing answers this today, and this spec does not
  add it. `front-office audit` checks the season, not the latest run: every played game
  has a boxscore, every scoring period has a roster captured after it closed, and the
  league snapshots postdate the season. A run that lands its schedule and then fails
  shows as fresh here, and shows in the audit only once a game or a period is missing.
  → Written down as the remaining limit (R5.1); not solved.
- **Choosing thresholds from evidence.** There is none: the 2026 landing zone holds four
  capture days for `espn`, six for `mlb` and one for `idmap`, all taken after the season
  ended. → The two daily feeds keep the thresholds they have. The id map's was the owner's
  choice: 14 days, warn only (2026-10-10).
- **Proving it in CI.** Freshness errors on the fixtures by design, so it cannot be a
  gate. → What CI holds is the declarations. The ages are checked by hand, on the
  fixtures, on a scratch copy and on the real season.

## Requirements

### R1. One freshness result per feed, for the capture that marks a run

- R1.1 THE SYSTEM SHALL declare one source table for each feed held in
  `raw.api_responses`, each reading that same relation and each with a freshness filter
  that selects only the feed's run marker, in the latest season that has one:

  | feed | run marker | why this capture |
  |---|---|---|
  | `mlb` | `endpoint = 'schedule'`, latest season | landed first by every full run, and alone by `--only schedule`; not landed by `--only players` or `--only boxscore` |
  | `espn` | `endpoint = 'settings'`, latest season | the first call that needs the login; landed by the full run and by `--only matchups`, not by `--only pro-schedule` |
  | `idmap` | `endpoint = 'player_id_map'` | its only endpoint. Its captures carry no season, so it has no season clause |

  The latest season is the greatest `season` in `partitions` among the feed's own
  marker captures, read in the filter itself: nothing has to be edited or passed when a
  new season starts. (Scoping to it was the owner's decision, 2026-10-10, second design
  review.) A marker is the first league or season call of a run, so a run limited to
  that call counts as a run: `--only schedule` and `--only matchups` both do.

  (Which capture marks a run was the owner's decision: these, 2026-10-10, PR #125.)
- R1.2 WHEN `dbt source freshness` is run, THE SYSTEM SHALL report exactly one result
  per feed, whose `max_loaded_at` is the newest `fetched_at` of that feed's run marker,
  read as UTC.
- R1.3 `raw.api_responses` itself SHALL carry no freshness check: the one age for the
  whole table is the fault being removed, and SHALL NOT appear beside the three.
- R1.4 WHEN one feed's newest run marker is older than its error threshold and another's
  is within its warn threshold, THE SYSTEM SHALL report the first as `error` and the
  second as `pass`.
- R1.5 WHEN a feed's newest capture is not its run marker (a pro schedule landed without
  the login; a player list landed alone), THE SYSTEM SHALL report the age of the run
  marker and not of that capture.
- R1.6 WHEN a marker capture of an earlier season is newer than every marker capture of
  the latest season (a past season fetched again), THE SYSTEM SHALL report the age of
  the latest season's newest marker.
- R1.7 IF no row matches a declaration's filter, THEN THE SYSTEM SHALL NOT report
  `pass`: dbt reads the age as that of year 1, which is `error` where there is an error
  threshold and `warn` where there is only a warn threshold (`idmap`).

### R2. Thresholds

- R2.1 The `mlb` and `espn` declarations SHALL warn after 36 hours and error after 7
  days: the thresholds the table has today, unchanged.
- R2.2 The `idmap` declaration SHALL warn after 14 days and SHALL have no error
  threshold. (The owner's choice, 2026-10-10. See design, *Thresholds*.)

### R3. Every feed with fixtures is declared

- R3.1 IF a feed has a committed capture in `fixtures/landing/`, read through
  `LandingZone.committed`, and no freshness declaration is filtered to it, or a
  declaration is filtered to a feed with no such capture, THEN THE SYSTEM SHALL fail the
  test suite, naming the feed.
- R3.2 IF a declaration's run marker names an endpoint of which its feed has no
  committed capture in `fixtures/landing/`, THEN THE SYSTEM SHALL fail the test suite,
  naming the endpoint.
- R3.3 IF two declarations are filtered to the same feed, or a declaration under the
  freshness source has no filter, or its filter names more than one feed or more than
  one endpoint (a season clause copied from another feed), THEN THE SYSTEM SHALL fail
  the test suite.
- R3.4 IF a declaration under the freshness source does not read `raw.api_responses`
  (`schema: raw`, `identifier: api_responses`), or its `loaded_at_field` is not the
  expression that parses `fetched_at` as the UTC stamp it is, THEN THE SYSTEM SHALL fail
  the test suite.

  (A feed added with no fixtures is not caught: nothing lists the feeds the loader
  accepts, which takes each capture's feed from its sidecar. Such a feed would have no
  staging tests either.)

### R4. Nothing else moves

- R4.1 `dbt build` on the fixtures SHALL give the same PASS, WARN and ERROR counts
  before and after: the new declarations have no models, no tests and nothing reading
  them.
- R4.2 No gate and no CI job SHALL run `dbt source freshness` (spec 0013, R4.3).

### R5. The record

- R5.1 The source YAML and the README SHALL say: that freshness is one age per feed;
  which capture marks a run of each feed and why; that it is still dormant and what
  wakes it; that a marker counts only in the latest season that has one; and its
  remaining limits: a run that starts and then fails shows as fresh, there is one age
  for `espn` however many leagues are fetched, and a later season's marker landed early
  moves the scope to that season.
- R5.2 The source YAML and the README SHALL no longer give "one age for a table holding
  three sources" as a known limit.

## Expected values

Read-only on 2026-10-10. The real season's values are from a query on
`data/warehouse.duckdb`; the fixtures' are from `dbt source freshness --target ci` on a
copy of the fixture warehouse, with the declarations of this design spiked in.

| Check | Expected | How to verify |
|---|---|---|
| Results reported, fixtures and real season | 3: `mlb_runs`, `espn_runs`, `idmap_runs`. No result for `raw.api_responses` | `target/sources.json` after `dbt source freshness` |
| `max_loaded_at`, fixtures | all three `2026-04-30T16:00:00+00:00`. (The whole table's is `2026-05-02T16:00:00+00:00`, a boxscore correction, which no longer counts for `mlb`) | same, `--target ci` |
| Status, fixtures | mlb `error`, espn `error`, idmap `warn`; exit 1 | same |
| `max_loaded_at`, real season | each run marker's `max(fetched_at)` in its latest season, at the time of the run. On 2026-10-10: mlb `2026-10-07T22:11:16`, the 2026 schedule (not the feed's newest, `2026-10-09T19:42:27`, a player list, nor the newest schedule, `2026-10-08T16:38:27`, which is 2018's); espn `2026-10-07T17:16:57`, the 2026 settings (not `2026-10-08T16:38:28`, 2018's); idmap `2026-09-26T17:36:54`; later if anything was fetched since | `dbt source freshness` against `select source, endpoint, json_extract_string(partitions, '$.season') as season, max(fetched_at) from raw.api_responses group by all` |
| Status, real season | each follows its own age and thresholds; `idmap` is `warn` once its newest capture is 14 days old (from 2026-10-10T17:36:54Z if it is not fetched again), never `error` | same |
| One feed stale, one fresh (R1.4), scratch copy of the fixtures with the `espn` settings rows given a stamp one hour old | espn `pass`; mlb `error` | by hand, task 4 |
| A capture that is not the marker (R1.5), same scratch copy with a `pro_schedule` row given a stamp one hour old and settings left as they are | espn `error`, `max_loaded_at` `2026-04-30T16:00:00+00:00` | by hand, task 4 |
| An earlier season fetched again (R1.6), scratch copy with the 2025 `espn` settings and the 2025 `mlb` schedule given a stamp one hour old | espn `error` and mlb `error`, both `max_loaded_at` `2026-04-30T16:00:00+00:00`. (Spiked 2026-10-10: without the season clause both read the restamped capture and `pass`) | by hand, task 4 |
| No row matches (R1.7), scratch copy with the `idmap` rows deleted | idmap `warn`, `max_loaded_at` `0001-01-01T00:00:00+00:00`. (Spiked 2026-10-10 with filters that match nothing: `warn` when warn-only, `error` with an error threshold) | by hand, task 4 |
| `dbt build`, fixtures | PASS=652 WARN=3 ERROR=0 of 660, as measured on the tree merged as `8333acd` | `.agentic/gates` |
| Sources in the docs site | 4 source tables in place of 1 | the site builder's printed counts |
| Models' `source()` calls | unchanged | `git diff --stat` shows no `.sql` file |
