# Settled boxscores: a game is final only when a capture postdates its settle window — requirements

Issue: #30 · Tier: M · Status: draft

## Problem

MLB's scorers revise a game's statistics for days after it ends, so a boxscore stays
refetchable for a 7-day settle window. The fetch logic decides whether that window is
over from today's date and the game's official date alone. Review finding
[R4](../../reviews/2026-09-27-code-review.md#r4--p1-the-settle-window-refresh-can-skip-the-corrections-it-is-intended-to-capture):
a game fetched the night it was played and next looked at eight days later is skipped,
although no capture was ever taken after the corrections could have landed. A week
without runs freezes every game played before it. Step 0 worked round this with
`--refresh`, which refetches everything.

The official date is also a weak clock. A game suspended and resumed keeps its original
official date: game 824912 of 2026 has official date 2026-06-16 and finished on a session
that started 2026-06-17T18:00Z. The reviewer's follow-up asks for a completion boundary
that is validated or conservative, for instants rather than dates, and for the fix not to
be a comparison with the official date.

The audit already judges settlement from captures, read-only, but by dates and by its own
rule, so the fetch logic and the audit can disagree.

## Goals

- A game is skipped only when a committed capture was taken at least the settle window
  after a point at which the game is known to have been over.
- That point comes from what was landed, not from the official date, today's date or a
  timezone.
- A capture taken before a game's final session started never starts the clock.
- The fetch logic and the audit give the same answer, from one definition.
- A missed week of runs repairs itself on the next run, without `--refresh`.

## No-gos

- **No change to the settle window.** Seven days stays an operational policy, not proof
  that no later correction occurs; `--refresh` remains for anything later.
- **No change to any dbt model, seed, fixture, sidecar or to the raw table.** The rule
  needs only `fetched_at`, which every sidecar already has.
- **No reading of boxscore payloads to decide what to fetch**, and no reading of older
  schedule captures: only the newest schedule, which the backfill already reads.
- **No working out when a game actually ended.** Nothing landed records it.
- **No request to MLB against the real landing zone by an agent.** Tests use a fake
  transport; the real season is verified by reading, and the live run is the owner's.
- **Not the schedule's own freshness.** Which schedule capture is "newest" and how often
  it is fetched are unchanged.

## Rabbit holes

- *Deriving the end time from first pitch plus duration in the boxscore's `info` text* →
  free text, in ballpark-local time, and silent on a resumed session.
- *Tracking the first schedule capture that showed each game Final* → 3.5 MB per
  schedule capture, one per run; the game's own first boxscore capture is the same fact
  from a sidecar.
- *Recording the game's state in the boxscore sidecar (`source_status`, as rosters do)* →
  the boxscore response carries no status, so it would be a copy of the schedule the
  rule already reads.
- *Per-timezone "day 7"* → instants only; a day is 24 hours.
- *Finding out how MLB codes a suspended game before it resumes* → not in what is
  landed; R1.2 and R2.7 hold the game open, or reopen it, once its later session is listed.

## Requirements

### R1. When a game is known to have been over

- R1.1 THE SYSTEM SHALL take as a game's last scheduled start the latest `gameDate`
  among all entries for its `gamePk` in the newest landed schedule of the season.
- R1.2 THE SYSTEM SHALL take as a game's first-final capture the earliest committed
  boxscore capture of that game and season whose `fetched_at` is later than the game's
  last scheduled start.
- R1.3 IF any entry for a played game has a missing or unparseable `gameDate` THEN THE
  SYSTEM SHALL treat the game as having no last scheduled start and no first-final
  capture, and log a warning naming it.
- R1.4 THE SYSTEM SHALL compare `fetched_at` and `gameDate` as UTC instants, and SHALL
  NOT use the official date, the resume date, today's date, the current time or any
  timezone in deciding what is settled.

### R2. A game is settled only by a later capture

- R2.1 THE SYSTEM SHALL treat a game as settled if and only if it has a first-final
  capture and some committed capture of it has a `fetched_at` at least the settle
  window (7 days, 168 hours) later than the first-final capture's.
- R2.2 WHEN a boxscore backfill runs without `--refresh` THE SYSTEM SHALL fetch every
  played game that is not settled and skip every game that is.
- R2.3 WHEN a boxscore backfill runs with `--refresh` THE SYSTEM SHALL fetch every played
  game.
- R2.4 THE SYSTEM SHALL decide what to fetch from the newest schedule and from sidecars,
  without reading any boxscore payload.
- R2.5 THE SYSTEM SHALL count only committed captures, and only those of the same season.
- R2.6 THE SYSTEM SHALL leave `--limit`, the handling of a failed game, rejected
  credentials and a collision as they are.
- R2.7 THE SYSTEM SHALL decide settlement afresh on every run and every audit, from the
  newest schedule and the captures then committed, and SHALL NOT store it. WHEN a newer
  schedule gives a game a later last scheduled start than its first-final capture THE
  SYSTEM SHALL treat the game as not settled again.

### R3. The audit uses the same rule

- R3.1 THE SYSTEM SHALL have the audit judge boxscore settlement by the same functions
  the fetch logic uses, and SHALL NOT use the official date or `resumeGameDate` for it.
- R3.2 THE SYSTEM SHALL have the audit warn of every played game that has captures but
  is not settled and whose settle window has closed as of the audit's time, naming the
  command that settles it, which needs no `--refresh`.
- R3.3 THE SYSTEM SHALL have the audit report, as information, the number of games whose
  settle window is still open.
- R3.4 THE SYSTEM SHALL have the audit warn of every played game whose captures all
  predate its last scheduled start.
- R3.5 THE SYSTEM SHALL decide whether an unsettled game's window has closed against
  the current instant by default, and against the end of the given Eastern date when
  `--today` is passed. `--today` moves only that threshold: every committed capture is
  still counted, whenever it was taken.

### R4. Tests

- R4.1 THE SYSTEM SHALL replace the tests that assert the date rule
  (`test_refetches_inside_the_settle_window`, `test_skips_a_settled_game`,
  `test_settle_window_boundary_is_inclusive_of_the_seventh_day`,
  `test_backfill_skips_already_settled_games`,
  `test_settle_evidence_needs_a_capture_after_the_window`,
  `test_a_resumed_game_settles_from_its_resume_date`) with tests of the capture rule.
- R4.2 THE SYSTEM SHALL have tests for: a missed week of runs; a game captured only on
  the day it was played; a game with an old official date first captured late; a
  resumed game with a capture taken before its resumed session started; and a settled
  game that a newer schedule gives a later session.

## Expected values

Measured on the real landing zone on 2026-10-07, read-only.

| Check | Expected | How to verify |
|---|---|---|
| Played games in the newest schedule (`20261005T121147Z`) | 2,429 of 2,430 scheduled; 1 cancelled | `games_from_landed_schedule` |
| Committed boxscore captures, 2026 | 4,923 over 2,430 games, from four runs: `20260926T152516Z` (5), `20260926T152526Z` (2,398), `20260928T215618Z` (91), `20261005T121147Z` (2,429) | `LandingZone.committed(source="mlb", endpoint="boxscore")` |
| Schedule entries with a parseable `gameDate` | 2,459 of 2,459, all UTC (`Z`) | one-off script |
| Captures that predate their game's last scheduled start | 0 | the new functions over the real landing zone |
| Settled games | 2,402 | the same |
| Not settled | 27: official date 2026-09-26 (13) and 2026-09-27 (14), all first captured `20260928T215618Z` and last captured `20261005T121147Z`, 6.6 days later | the same |
| Games the fetch logic would fetch, no `--refresh` | those 27; 2,402 skipped | the fetch decision for each played game; no network |
| Audit, as of now | a warning for 27 games whose window closed at 2026-10-05T21:56:18Z; no "still in settle window" line | `uv run front-office audit --season 2026` |
| The resumed game, 824912 | last scheduled start 2026-06-17T18:00:00Z; settled | the same |
| Files changed under `dbt/` or `fixtures/` | none | `git diff --stat main` |
