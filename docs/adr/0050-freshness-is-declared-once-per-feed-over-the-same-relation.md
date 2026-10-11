# 0050. Freshness is declared once per feed over the same relation, and is the age of the feed's run marker in its latest season

- Status: accepted
- Date: 2026-10-10
- Spec: [0114-freshness-per-feed](../specs/0114-freshness-per-feed/design.md) · Issue: #114

## Context

`raw.api_responses` holds three feeds (`mlb`, `espn`, `idmap`) and has one source
freshness check. dbt computes freshness per declared table, as the age of its newest
row, so the one check reports the freshest feed and hides the others. On the real
warehouse on 2026-10-10 the id map was fourteen days old behind a table one day old.

Splitting by feed alone leaves the same fault inside a feed. A full `espn` run lands
ESPN's public pro schedule first, with no login, and settings second, with one; when the
login expires the run still lands a pro schedule. A `mlb` run can be limited to the
player list: on the real warehouse the feed's newest capture is such a run, a day newer
than its newest schedule. And some endpoints are fetched only when there is something to
fetch: an off day lands no boxscore.

Nor does a capture's endpoint say which season it belongs to. Seasons 2018 to 2025 were
fetched for #57, each landing a schedule and a settings capture, and on the real
warehouse the newest of both are the 2018 season's, a day newer than the 2026 season's
own.

Spiked on dbt 1.12.5 (spec 0114, *What was measured*): three declarations with
`identifier: api_responses` and a `freshness.filter` each give three ages; with the
check removed from `raw.api_responses` itself, dbt reports exactly those three. A
second spike gave a past season's markers a stamp one hour old: without a season clause
both feeds read `pass`; with one, both read `error` at the current season's stamp.

Freshness is dormant: nothing runs it until the 2027 daily schedule (spec 0013).

## Decision drivers

- A stalled feed must show, whatever the others are doing, and an expired ESPN login is
  the likeliest stall.
- A day with nothing to fetch must not warn.
- Freshness should stay dbt's own, which the README already explains and the docs site
  shows.
- The fixtures are stale by design, so whatever checks freshness cannot run in a build.
- Leave the lineage and the models alone.

## Considered options

How the ages are split:

1. **One declaration per feed over the same relation**, each with a freshness filter;
   models keep reading `raw.api_responses`.
2. **The same declarations, with every model re-pointed** at its feed's.
3. **A model of newest captures per feed and league, with a test.**
4. **A recency check in `front-office audit`.**

What a feed's age is the age of:

- a. **The feed's run marker**: the first league or season call of a run, which no run
  of another endpoint and no unauthenticated call lands.
- b. **Any capture of the feed.**
- c. **Every endpoint, each with its own age.**

Which season a marker counts in:

- i. **The latest season that has a marker**, read in the filter itself.
- ii. **Any season**, with a past-season backfill named as a limit.
- iii. **A season passed as a dbt variable** by whatever runs freshness.

## Decision

Chosen: **option 1 with a and i** (owner, 2026-10-10, PR #125; the season on the second
design review the same day).

The run markers are the schedule for `mlb`, settings for `espn`, and the id map's one
endpoint. The first two count only in the latest season that has one; the id map's
captures carry no season. `mlb` and `espn` keep 36 hours to warn and 7 days to error. `idmap` warns at
14 days and never errors; that number is the owner's choice, not a measurement.

Option 2 makes a declaration named for one feed return every feed's rows, since
`identifier` only renames. Option 3 puts a time-dependent test into every build, which
must then be excluded wherever the fixtures are built. Option 4 is a second definition
of freshness beside dbt's. Option b is refreshed by a capture that proves nothing.
Option c warns on every off day. Option ii leaves in the one case already in the data.
Option iii needs the right season supplied on every run, by a command that does not
exist yet.

## Consequences

- Good: `dbt source freshness` gives three ages, and an expired ESPN login shows as a
  stale `espn`.
- Good: no model, macro or test changes.
- Bad / accepted cost: three source tables in the docs site that no model reads.
- Bad / accepted cost: a run that lands its marker and then fails shows as fresh.
  Nothing checks that the latest run landed everything: `front-office audit` checks the
  season (every played game has a boxscore, every period a roster captured after it
  closed), not the run.
- Bad / accepted cost: one age for `espn` however many leagues are fetched. A stalled
  league hides behind a live one. Option 3 is the one that would see it.
- Good: fetching a past season again does not make a stalled feed look fresh.
- Bad / accepted cost: the season clause reads `partitions` with DuckDB's JSON function
  in a YAML filter, outside the `fo_json_*` macros the models use. It is one file to
  rewrite for BigQuery.
- Bad / accepted cost: a later season's marker landed early moves the scope to that
  season. Freshness is not run out of season.
- Bad / accepted cost: the markers are read from the order of calls in today's
  `backfill` commands. A daily command that fetches differently needs them checked again.
- Follow-ups: check the markers against the 2027 daily command when it exists; revisit
  the league limit when a second league is fetched daily; choose the id map's threshold
  from evidence once a season of daily runs exists.
