# 0020. A capture taken before a game's last scheduled start does not start the settle window

- Status: proposed
- Date: 2026-10-07
- Spec: [0030-settled-boxscores](../specs/0030-settled-boxscores/design.md) · Issue: #30

## Context

[ADR 0019](0019-a-boxscores-settle-window-runs-from-its-first-capture.md) starts a
game's settle window at its first boxscore capture, on the ground that a boxscore is
requested only for a game listed as played. A suspended game tests that ground. If MLB
lists a suspended game as final before it resumes, its boxscore would be captured with
the resumed innings missing, and seven days later it would be settled that way. How MLB
lists such a game cannot be read from what is landed: the one suspension of 2026 was in
June and the first schedule capture is from September. MLB's status table says a
suspended game is `Live`, which would keep it out of the backfill; no capture confirms it.

What the landed schedule does show, for game 824912: two entries with official date
2026-06-16, one with `gameDate` 2026-06-16T23:15:00Z and `resumeDate`
2026-06-17T18:00:00Z, the other with `gameDate` 2026-06-17T18:00:00Z and `resumedFrom`
2026-06-16T23:15:00Z. For all 28 postponed games the played entry's `gameDate` equals
the postponed entry's `rescheduleDate`.

The owner asked for more evidence than one season's schedule, so MLB's public API was
read on 2026-10-07 (details in the spec's design.md). All 15 resumed games of 2022–2025
have the same two-entry shape, the first entry's `resumeDate` equal to the second's
`gameDate`. In the live feeds of four resumed games the first play starts within three
minutes of the first entry's `gameDate`; in three, the last play ends about two hours
after the second entry's `gameDate`; the fourth (716404, 2023) was never resumed and was
declared complete, its last play three days before the listed resume start. MLB's status
table classes all 34 `Suspended` states as `Live`, where the backfill takes only `Final`.

So `gameDate` is the scheduled start of that entry's session, and `resumeDate` is a
planned restart: not a completion, and not always played. What an MLB field means is the
owner's decision (AGENTS.md).

## Decision drivers

- A boxscore missing part of a game must never be settled.
- Do not depend on behaviour of the source that cannot be observed.
- Use a field only for what it can prove.
- Read nothing the fetch logic does not already read.

## Considered options

1. **Ignore captures older than the game's last scheduled start**, the latest `gameDate`
   among its entries in the newest schedule.
2. **Nothing** — trust that a suspended game is not listed as played until it finishes.
3. **Restart the window whenever the game's schedule entry changes** between captures.
4. **Start the window at the resume date** (the audit's present rule).

## Decision

Chosen: **option 1**, by the owner on 2026-10-07, after the evidence above.

A game's first-final capture is its earliest committed capture with a `fetched_at`
later than the latest `gameDate` among all of the game's entries in the newest landed
schedule. Earlier captures are kept and loaded as always; they only do not start the
window. A game with any missing or unparseable `gameDate` among its entries is never
settled, and that is reported. Settlement is recomputed on every run from the newest
schedule, so a later session that appears after a game has settled reopens it.

A game cannot be over before its last session starts, so `gameDate` is used only as a
lower bound, which is all a scheduled start proves. Option 2 may well be true but cannot
be shown. Option 3 covers the same case by storing or re-reading schedule entries.
Option 4 treats a restart as a completion.

## Consequences

- Good: once the schedule shows a later session, the game is held open or reopened,
  however MLB listed it before.
- Good: `resumeGameDate` and the official date drop out of the settle logic.
- Good: on 2026 no capture predates its game's last scheduled start, so nothing changes
  for the data already landed.
- Bad / accepted cost: the rule now depends on `gameDate` being present. It is in 2,459
  of 2,459 entries.
- Bad / accepted cost: if MLB ever moves a `gameDate` later than the real start, captures
  are ignored until one is later still. It can only delay settling.
- Bad / accepted cost: if MLB lists a suspended game as played before its later session
  is in the schedule, the game can be settled on a partial boxscore until that session
  appears. MLB's status table says it does not; the owner accepted the gap on 2026-10-07.
- Bad / accepted cost: a resume that is listed and never played (716404) leaves the last
  scheduled start later than the real end, which delays settling.
- Follow-ups: #69 checks the first suspension of 2027.
