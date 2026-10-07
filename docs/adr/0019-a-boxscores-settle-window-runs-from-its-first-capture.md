# 0019. A boxscore's settle window runs from the game's first capture

- Status: accepted
- Date: 2026-10-07
- Spec: [0030-settled-boxscores](../specs/0030-settled-boxscores/design.md) · Issue: #30

## Context

A boxscore stays refetchable for 7 days because MLB's scorers revise statistics after a
game. The fetch logic measures those 7 days from the game's official date to today, so a
game captured once and next visited after the window is skipped with no capture from
after the corrections (review finding R4). The reviewer's follow-up asks for a completion
boundary that is validated or a conservative first-observed-Final, in instants with the
timezone question settled, and not a comparison with the official date.

Measured on 2026: nothing landed records when a game ended. The schedule gives each
session's scheduled start (`gameDate`) and an official date, which differs from the UTC
date of the start for 582 played entries. A boxscore is requested only for a game the
landed schedule lists as played. `fetched_at` is the stamp of the run.

## Decision drivers

- Never call a game settled on a capture that could predate a correction.
- Use a point at which the game is known to be over, not one at which it is assumed to be.
- No timezones, and no dependence on when the fetch logic runs.
- Cheap to decide: sidecars, not payloads.
- The audit and the fetch logic must agree.

## Considered options

1. **The game's own first boxscore capture** — it exists only because the game was
   listed as played.
2. **The first schedule capture that lists the game as played.**
3. **The last scheduled start plus a margin** for the length of a game.
4. **The official date, or the resume date** — today's rule, moved onto captures.

## Decision

Chosen: **option 1**, by the owner on 2026-10-07.

A game is settled if and only if some committed capture of it has a `fetched_at` at
least 7 days (168 hours) later than that of its first capture. Which captures can be
"first" is narrowed by
[ADR 0020](0020-a-capture-before-a-games-last-scheduled-start-does-not-count.md). The
comparison is between UTC instants and is inclusive. Today's date, the official date and
the resume date play no part.

The first capture can only be later than the true end of the game, so the window can
only run long. Option 2 is the same boundary read from 3.5 MB schedule captures, one per
run, instead of from a sidecar. Option 3 settles a backfilled season in one pass but
rests on how long a game can take, which a suspension breaks. Option 4 is what the
follow-up rules out.

## Consequences

- Good: a missed week of runs repairs itself on the next run, without `--refresh`.
- Good: no dates or timezones anywhere in the rule.
- Good: needs no new sidecar field, so every capture already landed is judged alike.
- Bad / accepted cost: a season backfilled after it ended is not settled until a second
  pass at least 7 days later, although its real window closed long before.
- Bad / accepted cost: 27 games of 2026-09-26 and 2026-09-27, first captured
  `20260928T215618Z` and last captured 6.6 days later, become unsettled until the next
  run fetches them once more. The date rule calls them settled.
- Bad / accepted cost: one or two more captures per game in daily operation, 3.7 to 4.2 GB a season
  against 3.2 GB.
- Bad / accepted cost: `fetched_at` is stamped when a run starts, seconds before its
  requests.
- Follow-ups: none required. The captures a window now collects would show whether
  corrections ever arrive after 7 days.
