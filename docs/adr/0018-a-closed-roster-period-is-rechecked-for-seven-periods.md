# 0018. A closed roster period is fetched again for seven periods

- Status: proposed
- Date: 2026-10-06
- Spec: [0027-settled-roster-captures](../specs/0027-settled-roster-captures/design.md) · Issue: #27

## Context

[ADR 0016](0016-a-roster-period-is-settled-by-the-status-in-its-own-response.md) shows a
period closed once a capture records the league past it. Closed is not quite final: a
commissioner can edit a past period's roster, and the owner confirmed on 2026-10-06 that
this can happen in this league and should be accommodated if it is not too expensive. A
capture taken the morning after a period closed would otherwise be kept for good, and a
correction made that afternoon would never reach the warehouse.

No such edit has been identified in the 2026 data, so how often and how late they happen
is not measured. A roster capture is 2.4 MB, and nothing landed is ever deleted.

## Decision drivers

- A correction to a recent day should arrive without anyone asking for it.
- Ingestion fetches and saves; it does not interpret payloads.
- The cost in requests and disk should be bounded and known in advance.
- An older edit must still have a way in, and a finished season must not be left stale
  unnoticed.

## Considered options

1. **Re-check for a fixed number of periods after the close** — settled means evidence
   greater than the period plus 7.
2. **Nothing automatic** — `--refresh` by hand when an edit is known.
3. **Refresh every period on every run.**
4. **Find edits in ESPN's activity log** and fetch only the periods they touch.
5. **Re-check until the period's matchup ends.**

## Decision

Chosen: **option 1, with a window of 7 scoring periods**, plus an audit warning when a
finished season has a period with no capture taken after the final period.

A period is fetched on every run until one of its captures records a latest period
greater than the period plus 7. Seven periods is a scoring week, the span in which a
lineup mistake still matters to a matchup. With one run a day that is nine captures per
period: 9 requests a run and about 3.9 GB a season, against 0.9 GB with no window.

Option 2 is the cheapest and relies on remembering. Option 3 catches everything for
about 39 GB a season and 180 requests a day. Option 4 is the precise signal, but whether
a commissioner's lineup edit is logged with the period it changes is unverified, and the
fetcher would have to interpret the log. Option 5 needs the matchup schedule in the
fetcher and misses an edit made the day after a matchup ends.

## Consequences

- Good: an edit within a week of the day is landed by the next run, and dbt reads it
  because it reads the newest capture.
- Good: the rule stays one comparison on a number already in the sidecar.
- Good: the re-check captures give #66 its comparisons for free.
- Bad / accepted cost: about 3 GB a season more than no window, most of it identical
  rosters.
- Bad / accepted cost: an edit more than 7 periods old is missed until a `--refresh`.
  The audit's season-close warning bounds that at the end of the season.
- Bad / accepted cost: periods 179 and 180 of 2026 (evidence 186) are fetched once more
  on the owner's next run.
- Follow-ups: revisit the window with what #66 shows about how often a re-check differs.
