# 0030. The fixture season runs from a starter's earlier start to the fixture days, with a gap

- Status: proposed
- Date: 2026-10-09
- Spec: [0093-earlier-fixture-day](../specs/0093-earlier-fixture-day/design.md) · Issue: #93
- Amends: [0025](0025-fixture-rosters-are-taken-from-the-mlb-fixture-days.md), for the number and numbering of fixture periods

## Context

ADR 0029 puts a free-agent start in the replacement pool only if the pitcher was a
starter on his earlier appearances of the season. The fixtures are two consecutive days,
so their start pool is empty, fixture starts have no value and CI warns (#93).

An earlier day cannot simply be added as MLB data. The models hold a season to two rules:
MLB's earliest game is ESPN's first scoring period, and periods are consecutive days
from it (ADR 0023). And starters pitch in a rotation, a turn every fifth or sixth day,
so a start and the same pitcher's previous turn are at least six periods apart on any
dates. Free agent 678394 started fixture game 822821 for Boston on 2026-04-29; his
previous turn was Boston's game 824854 on 2026-04-24: real periods 36 and 31.

A spike on 2026-10-09 built a seven-period fixture season both ways. With a roster on the
earlier day: `PASS=480 WARN=3`, isolation 0, multi script unchanged. Without one:
`PASS=479 WARN=4`, because `stg_espn__scoring_periods_have_game_lines_to_check` then
reports period 1, and the multi tree's one-period 2027 season is left with no roster.

## Decision drivers

- A fixture is real data cut down, never data made to fit (ADR 0025).
- Keep the two fixture days, their boxscores and postponed game 823471.
- No test weakened, no model changed for a fixture's sake.
- CI should end with fewer warnings, not a different one.
- Small committed files.

## Considered options

1. **A seven-period season, 2026-04-24 to 2026-04-30, with data on periods 1, 6 and 7 and
   a roster on each.**
2. **The same, with MLB and pro-schedule data only on period 1**: what #93 first asked.
3. **Rosters and calendars for all seven periods.**
4. **Invent the earlier start** in a synthetic boxscore.
5. **Leave the pool empty in CI.**

A shorter season is not among them: the rotation rules it out, and a start on short
rest is an opener's or an emergency's, which ADR 0029 keeps out of the pool.

## Decision

Proposed: **option 1**. The owner decides; the question that most needs an answer is
option 1 against option 2.

The fixture season is real periods 31 to 37, numbered 1 to 7 by offset, so a fixture
period keeps its real distance from the others. Calendars (MLB schedule, pro schedule),
rosters with game lines and boxscores exist for periods 1, 6 and 7; periods 2 to 5 are
the days between two turns, with nothing landed. The earlier boxscore is one named
game, 824854, the previous turn of a fixture starter,
and generation fails unless a pitcher starts in it, starts again in a later fixture
boxscore, and is on no fixture roster that later day.

Option 2 is smaller by about 0.35 MB and matches the issue as written, but it trades the
pool warning for the game-lines one and forces a redesign of the multi tree's 2027
season. Option 3 adds about 1.2 MB of rosters with no boxscore to meet them. Option 4 invents
data in the one place the pool rule is exercised. Option 5 is what #93 was opened to end.

## Consequences

- Good: CI computes a start level and values every fixture start; warnings return to 3.
- Good: the earlier day is a full fixture day, so the game-line tests read a third
  period and the multi script is untouched.
- Good: the fixture cannot lose its qualifying pitcher unnoticed.
- Bad / accepted cost: fixtures grow from 852 KB and 2.3 MB to about 1.2 MB and 2.9 MB.
- Bad / accepted cost: the roster fixtures are renumbered 1, 2 to 6, 7, period 1's
  roster is a different day, and every 2027 capture in the multi tree moves to
  2027-04-23. One large, generator-made diff.
- Bad / accepted cost: the fixture season has four periods with no data, which no real
  finished season has. They are the days between two turns of a rotation and any
  fixture of this rule has them, unless it carries rosters for them. No test objects.
- Bad / accepted cost: the start pool in CI is one start. It proves the path, not the
  level.
- Bad / accepted cost: one game id is named in the generator.
- Follow-ups: `rec_fantasy__category_wins_added` is still empty in CI, for want of a
  re-scorable fixture matchup; not addressed here.
