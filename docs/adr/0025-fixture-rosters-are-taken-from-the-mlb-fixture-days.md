# 0025. Fixture rosters are taken from the MLB fixture days, with ESPN's game lines

- Status: accepted
- Date: 2026-10-07
- Spec: [0074-roster-fixtures-with-game-lines](../specs/0074-roster-fixtures-with-game-lines/design.md) · Issue: #74

## Context

The committed fixtures are a two-day season. MLB's schedule, the boxscores and ESPN's pro
schedule are from 2026-04-29 and 2026-04-30 (real scoring periods 36 and 37). The roster
fixtures are from real periods 100 and 101, 2026-07-02 and 2026-07-03, renumbered to
look like the same two days, and they omit ESPN's per-game stat lines. Three tests that
compare those lines with the schedule or with MLB's games therefore have nothing to
read in CI, and lines from the July rosters would contradict the April games.

A spike on 2026-10-07 rebuilt the rosters from periods 36 and 37 with their lines: three
fixture files changed, every gate passed, and ESPN's games with stats were 13 and 11,
the MLB games played on those dates.

## Decision drivers

- A fixture should be real data cut down, never data made to fit.
- A test that passes in CI should have compared something.
- Member data never reaches a fixture: allowlist, not scrubbing.
- Keep the postponed game that the MLB fixture dates were chosen for.

## Considered options

1. **Take the rosters from the MLB fixture days**, with the stat lines of those periods.
2. **Move the MLB and pro schedule fixtures to the rosters' days.**
3. **Keep the rosters and rewrite their lines' game ids** to games of the April days.
4. **Leave the rosters without lines** and keep the CI warning.

## Decision

Chosen: **option 1**, by the owner on 2026-10-07, with the allowlist below.

Rosters and the pro schedule are built from one pair of real scoring periods, 36 and 37,
and generation fails unless those periods fall on the MLB fixture dates. A roster entry
keeps the player's single-game stat lines of that period, each rebuilt from five fields:
`scoringPeriodId`, `statSourceId`, `statSplitTypeId`, `externalId`, `stats`.

`stats` is copied whole, every stat id ESPN sends, and not cut down to the categories
this league scores. The owner's reason: the project is meant to be general, not tailored
to one league's settings, so a fixture should carry what any league's models could read.

Option 2 loses postponed game 823471 and rewrites every MLB fixture. Option 3 invents
data. Option 4 leaves three tests guarding nothing between real-season builds.

## Consequences

- Good: the three game-line tests read real rows on every CI run.
- Good: CI's warnings fall from 6 to 3, and the one that says "could not be checked"
  goes because there is nothing to report.
- Good: the day mismatch cannot return unnoticed: generation checks it.
- Bad / accepted cost: the fixtures grow by about 1.5 MB.
- Bad / accepted cost: the allowlist is wider by five fields of game statistics. They
  are numbers keyed by ESPN's stat ids and a game id; no member field.
- Bad / accepted cost: the matchup and transaction fixtures are still from other days.
- Bad / accepted cost: `rec_espn__player_day_differences` has 308 rows in CI, not 21,
  because only 2 of the 24 games have a boxscore fixture (#81).
