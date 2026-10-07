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
June and the first schedule capture is from September.

What the landed schedule does show, for game 824912: two entries with official date
2026-06-16, one with `gameDate` 2026-06-16T23:15:00Z and `resumeDate`
2026-06-17T18:00:00Z, the other with `gameDate` 2026-06-17T18:00:00Z and `resumedFrom`
2026-06-16T23:15:00Z. For all 28 postponed games the played entry's `gameDate` equals
the postponed entry's `rescheduleDate`. So `gameDate` is the scheduled start of that
entry's session, and `resumeDate` is a restart, not a completion. What an MLB field
means is the owner's decision (AGENTS.md).

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

Chosen: **option 1**.

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
  appears.
- Follow-ups: the first suspension of 2027 will show how such a game is listed; nothing
  needs to change either way.
