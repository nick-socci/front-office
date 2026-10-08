# Roster fixtures on the fixture days — design

Issue: #74 · Requirements: [requirements.md](requirements.md) · Tasks: [tasks.md](tasks.md)

## Overview

The roster fixtures move from real scoring periods 100 and 101 to 36 and 37, the periods
of the two MLB fixture dates, which is where the pro schedule fixture already is. Each
roster entry also keeps the player's single-game stat lines for that period, rebuilt
from an allowlist of five fields. That is a change to one constant and one function of
`scripts/make_fixtures.py`, followed by regenerating both fixture trees. No model
changes. The three game-line tests then read real rows in CI: ESPN's games with stats
are 13 and 11, exactly the MLB games played on those dates, and every one is in the
fixture's pro schedule on the same period.

## Alternatives considered

| | A — rosters move to the MLB fixture days (chosen) | B — MLB and pro schedule move to the rosters' days | C — keep the rosters, add their lines, renumber game ids | D — leave it; the warning stands |
|---|---|---|---|---|
| Rosters, lines, pro schedule and MLB on the same real days | yes | yes | no: lines from July against games from April | no |
| The three tests compare real rows in CI | yes | yes | no: they would pass on invented ids | no |
| Keeps postponed game 823471 in the MLB fixture | yes | no | yes | yes |
| Fixture files rewritten | 2 rosters, id map | everything | 2 rosters, id map | none |
| Invents data | no | no | yes | no |

**A — rosters move.** The MLB dates were chosen for a reason that still holds: game
823471 was postponed on 2026-04-29 and made up on 2026-04-30, which exercises the
`stg_mlb__games` tie-break in CI. The roster periods were "two adjacent scoring periods
from mid-season", with no reason tied to those days. So the rosters move.

**B — MLB moves.** Symmetric on paper. It loses the postponed game, rewrites the
schedule, both boxscores, the synthetic correction and the pro schedule, and every test
that names game 823471 or those dates.

**C — keep the rosters and make their lines fit.** Rewrite each line's `externalId` to
a game of the April schedule. It loses because the fixture would then assert something
that never happened, and a test passing on it would prove nothing about real data.

**D — leave it.** The warning is honest and the real-season build covers the tests. It
loses because three tests then guard nothing against a change made between real-season
builds, which is what CI is for.

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0025](../../adr/0025-fixture-rosters-are-taken-from-the-mlb-fixture-days.md) | Fixture rosters are taken from the MLB fixture days, with ESPN's game lines | proposed |

## Detailed design

### `scripts/make_fixtures.py`

- `FIXTURE_SOURCE_SCORING_PERIODS = (36, 37)`, with a comment saying they are the real
  periods of `DEFAULT_DATES` and are used for rosters and the pro schedule alike.
  `FIXTURE_PRO_SCHEDULE_SOURCE_PERIODS` is removed and `build_espn_pro_schedule` reads
  the one constant.
- A check, run by `main()` before anything is written (R1.2): for each source period, the
  set of Eastern dates of its games in the landed pro schedule must be exactly the
  corresponding entry of the dates the script was given. Otherwise `SystemExit` naming
  the period, the dates found and the date wanted. This is what stops the constant and
  the dates drifting apart again, including when the script is run with other `--dates`.
- `latest_espn` passes `season=2026` to `landed(...)`, with the scoring period as a
  partition too where it has one, so the landing zone's own partition match selects the
  captures and no path is searched for a substring (R1.4). Before any ESPN fixture is
  built, the `league_id` partitions of the season's settings captures are collected
  through `LandingZone.committed`; more than one stops generation with the count (R1.5).
  The message gives the count, not the ids.
- `ESPN_STAT_LINE_FIELDS = ("scoringPeriodId", "statSourceId", "statSplitTypeId",
  "externalId", "stats")`.
- `build_espn_rosters`: after `rebuild(entry, ESPN_ROSTER_ENTRY_FIELDS)`, the entry's
  lines are taken from `entry.playerPoolEntry.player.stats`, kept when `statSourceId ==
  0`, `statSplitTypeId == 5` and `scoringPeriodId == source_period`, each rebuilt from
  `ESPN_STAT_LINE_FIELDS` with `scoringPeriodId` set to the fixture period. If any are
  kept they are written at `playerPoolEntry.player.stats`; if none, no key is added.
  These are the conditions `stg_espn__player_game_stats` applies when it reads a roster,
  so the fixture keeps what the model would keep and nothing else.
- `stats` is ESPN's map from stat id to number, copied whole, as the matchup fixture
  copies `scoreByStat`. A line also has `id`, `proTeamId`, `seasonId`, `appliedTotal`
  and `appliedStats` in the real payload; none is on the allowlist.
- The comments on `FIXTURE_SOURCE_SCORING_PERIODS` and `FIXTURE_FETCHED_AT` are brought
  up to date.

### `scripts/make_multi_fixtures.py`

No code change is expected: it derives everything from `fixtures/landing/`, relabels
the 2026 rosters for the second league, and cuts 2027 down to period 1, whose roster
keeps its lines with `scoringPeriodId` 1. In the spike it ran unchanged and the
isolation check passed. If regeneration shows otherwise, that is the stop condition of
R3.3, not something to patch around.

### What CI builds from it

- `stg_espn__roster_entries` and `stg_espn__roster_entry_slots` read the new rosters:
  307 and 306 entries.
- `stg_espn__player_game_stats` has rows. A line with an empty `stats` map yields none,
  which is why the lines name 15 games on period 1 and the model has 13: two games of
  that day were postponed and ESPN lists them with no stats.
- The id-map fixture is rebuilt for the players of the new rosters, as it always is.

### Comments

The headers of `stg_espn__scoring_periods_agree_with_espn_game_lines.sql`,
`stg_espn__scoring_periods_have_game_lines_to_check.sql` and
`stg_espn__player_game_stats_games_are_scheduled.sql` each say the fixture rosters carry
no game lines. They are corrected: in CI the tests read two periods of real lines; the
warning's header keeps its in-season reason and drops the CI one. SQL is not touched.

Specs 0070 and 0073 say the same in several places. They are the record of what was
approved and are not edited.

## Test strategy

| Requirement | Test | Catches |
|---|---|---|
| R1.1, R1.3 | pytest: the committed roster and pro schedule fixtures hold periods 1 and 2, and every roster line's game is in the pro schedule fixture on the same period | rosters and schedule built from different days again |
| R1.2, R5.2 | pytest on a made-up landing zone: a period whose games are on another date, or on two dates, stops generation | the constant and the dates drifting apart |
| R1.4, R1.5, R5.2 | pytest on a made-up landing zone: a newer period-36 roster of another season is not chosen; two leagues in 2026 stop generation | a fixture built from another season or league once one is landed (#57) |
| R2.1–R2.3, R5.1 | pytest of the committed rosters: five keys per line, source 0, split 5, the roster's own period; an entry with no line has no `stats` key | a projected or season-total line, or a field outside the allowlist, reaching a public file |
| R2.4, R3.4 | the existing fixture tests and the privacy test, unchanged | a lost roster field; member data |
| R3.1–R3.3 | `git status fixtures` after regeneration, in the build | an unrelated fixture changing with the landing zone |
| R4.1, R4.2 | the CI `dbt build`; a query of `ci.duckdb` | lines not reaching the model; a test failing on real rows |
| R4.3 | the isolation gate | a league-season's rows depending on another's |
| Expected values | the last task | numbers that moved since the spike |

## Risks

- The landing zone gains captures between the spike and the build and another fixture
  changes — low; nothing is being fetched — R3.3 stops the build.
- Fixtures grow by about 1.5 MB in the repo — certain — accepted; the two trees stay
  under 3.2 MB together.
- A later change to the allowlist lets a member field through — low — the privacy test
  rebuilds nothing but rejects the patterns, and the new pytest pins the five keys.
- `rec_espn__player_day_differences` grows from 21 to 308 rows in CI and looks alarming
  — certain — recorded here and in the expected values; it is the 22 boxscores the
  fixtures do not have, and no CI test reads it.

## Open questions

- **The matchup and transaction fixtures are still from other days.** The matchups are
  the season's first two, with `pointsByScoringPeriod` cut to real periods 1 and 2
  (2026-03-25 and 2026-03-26); the transactions are the first topics of the newest
  page. #74's title says "one real pair of days"; this spec makes that true of rosters,
  lines, the pro schedule and MLB, not of those two. The owner decides whether that is
  enough to close #74 or whether the rest becomes its own issue.
- **Why period 36's roster has a line for all 307 entries and period 37's for 178 of
  306.** Not looked into. The model keeps only lines with stats, and the tests pass on
  both.
- **Whether `…have_game_lines_to_check` should fail in CI and warn elsewhere.** dbt can
  set severity by target. Not proposed: one test behaving two ways is its own decision.

## Review log

| Source | Finding | Resolution |
|---|---|---|
| design-review | F1 (P1): matchup and transaction fixtures stay on other days, and whether that satisfies #74 is unresolved | Not changed: it is the owner's decision and is the first item under *Decisions for you* in the PR. The spec's title and goals claim only what it does |
| design-review | F2 (P2): the date check validates the 2026 pro schedule but not the season or league of the roster captures `latest_espn` picks | Changed: R1.4 and R1.5. Sources are selected by the `season` partition, and a second league in the season stops generation |

## Amendments
