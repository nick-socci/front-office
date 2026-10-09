# An earlier fixture day — design

Issue: #93 · Requirements: [requirements.md](requirements.md) · Tasks: [tasks.md](tasks.md)

## Overview

The fixture season grows from two periods to seven: real scoring periods 31 to 37,
2026-04-24 to 2026-04-30, numbered 1 to 7. Data exists for periods 1, 6 and 7 only.
Period 1 gains a roster, its pro-schedule and MLB-schedule games, and one boxscore, game
824854, in which free agent 678394 starts; he starts again in existing fixture game
822821 on period 6, so that start is in the pool. The change is to constants and the
period numbering of `scripts/make_fixtures.py`, a generation check, and regenerating
both trees. No dbt model, macro, seed or test SQL changes.

| Fixture period | 1 | 2–5 | 6 | 7 |
|---|---|---|---|---|
| Real period, date | 31, 04-24 | 32–35 | 36, 04-29 | 37, 04-30 |
| MLB schedule, pro schedule | 14 games | — | 13 (15 listed by ESPN) | 11 |
| Roster with game lines | new | — | was period 1 | was period 2 |
| Boxscores | 824854 (new) | — | 822821, 822907 | none, as today |
| What it gives the start pool | 678394's previous turn | the days between turns | 678394's start, a free agent | |

## Alternatives considered

| | A — seven periods, roster on each data day (chosen) | B — seven periods, period 1 MLB-only | C — all seven periods full | D — synthetic earlier start | E — leave it |
|---|---|---|---|---|---|
| Start pool has a played day in CI | yes | yes | yes | yes | no |
| CI warnings | 3 | 4 (a different fourth) | 3 | 3 | 4 |
| Real data only | yes | yes | yes | no | yes |
| Keeps game 823471 and existing boxscores | yes | yes | yes | yes | yes |
| Multi script unchanged | yes (spiked) | no: 2027 has no roster | yes | yes | yes |
| Fixture growth, both trees | about 1.0 MB | about 0.1 MB | about 4 MB | none | none |

**A.** Spiked: `PASS=480 WARN=3 ERROR=0`, isolation 0, three pytest to update.

**B — what the issue first asked.** Spiked for the base tree: it builds, the pool has its
day, and `stg_espn__scoring_periods_have_game_lines_to_check` warns for period 1, which
has MLB games and a rostered league but no game lines. The multi tree's 2027 season is
"period 1 only" and would have no roster, so `make_multi_fixtures.py` would need to
renumber a later period into it.

**C.** Four more rosters at about 300 KB each, three times over in the multi tree, for
days with no boxscore.

**D.** The correction snapshot is synthetic, but it tests a mechanism (latest snapshot
wins). An invented start would be the pool's only member.

**E.** Accepted in spec 0089 as temporary; #93 is its end.

Not an option: a shorter season. A starter's turn comes every fifth or sixth day, so a
start and the pitcher's previous turn are never fewer than six periods apart. The few
starts on shorter rest are openers and emergencies, the pitchers ADR 0029's role filter
is there to leave out. The empty periods 2 to 5 follow from that in A and B alike.

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0030](../../adr/0030-the-fixture-season-runs-from-a-starters-earlier-start.md) | The fixture season runs from a starter's earlier start to the fixture days, with a gap; a roster on each data day | proposed |

## Detailed design

### `scripts/make_fixtures.py`

- `DEFAULT_DATES = ("2026-04-24", "2026-04-29", "2026-04-30")` and
  `FIXTURE_SOURCE_SCORING_PERIODS = (31, 36, 37)`. The existing check pairs them and
  already refuses unequal lengths.
- Two small helpers replace `enumerate(..., start=1)` and `len(source_periods)`:
  the fixture number of a source period (`source - source_periods[0] + 1`) and the span
  (`source_periods[-1] - source_periods[0] + 1`). Used by `build_espn_pro_schedule`,
  `build_espn_rosters`, `build_espn_settings` (three fields) and `build_espn_matchups`
  (through `trim_scoring_periods`, whose default argument also becomes the span). For
  2025's `(1, 2)` both give what they give today.
- `build_mlb_boxscores` takes the played games of the dates of the last two source
  periods, sorted, first `FIXTURE_BOXSCORE_GAMES`, exactly as now, then appends
  `FIXTURE_HISTORY_GAME_PKS = (824854,)`. Without the restriction the earlier date's
  lowest id, 822827, would displace 822907. The correction snapshot is still made from
  the first boxscore written, 822821. A history game that is not landed is a
  `SystemExit`, not a skip.
- A new check, run by `main()` with the others before anything is written (R3.1). It
  reads the landed boxscores it is about to use, the landed rosters of the source
  periods and the landed id map, and requires one MLB person id that: has
  `stats.pitching.gamesStarted` ≥ 1 in a history game, with `outs` > 0 and plate
  appearances no greater than batters faced there; has `gamesStarted` in a later chosen
  game; and maps to no ESPN player id on any roster of that later game's period. A pitcher
  with no id-map row counts as unrostered, as he does in the model, where an unresolved
  roster entry has no `mlbam_player_id`. The conditions on the earlier start are the
  facts `fo_replacement_group` reads; for a single earlier appearance they are the whole
  rule. The macro stays the rule's one home: if it changes, the pool warning in CI says
  so, and this check is brought into line.
- Comments on `FIXTURE_FETCHED_AT`, `DEFAULT_DATES`, `FIXTURE_SOURCE_SCORING_PERIODS`
  and `build_espn_settings` are brought up to date. The stamp does not change: it is
  still the Eastern afternoon of the last date.
- The generator only writes. The old `scoring_period=2` roster directory is removed with
  `git rm` before regenerating (period 1's is overwritten in place).

### `scripts/make_multi_fixtures.py`

No change. It takes the base tree's first schedule date and roster period 1, which are
now 2026-04-24. 2027 becomes one period on 2027-04-23 with boxscore 1824854, and its
ESPN captures are restamped accordingly, so every 2027 capture directory is renamed. A
one-day season has an empty start pool; only the isolation check builds it, and that
compares rows, not warnings.

### What CI builds from it

- `stg_espn__scoring_periods`: seven rows for 2026. Periods 2 to 5 have a date, no pro
  game, no roster and no MLB game.
- Every period still belongs to exactly one matchup: the fixture matchups keep keys 1 to
  7 of `pointsByScoringPeriod`.
- `int_mlb__player_game_days`: 678394 has a start on 04-24 and on 04-29. On 04-29 his
  role to date is SP and he is on no roster, so that day is the start pool: 11 outs.
- The two fixture starts in lineups on 04-29 (543135 and 695684) are measured against
  it. 543135 is also started on 04-24, with no boxscore for his game that day.

### Tests and comments

- `test_make_fixtures.py`: the committed pro schedule holds periods 1, 6, 7 with 14, 15
  and 11 games on their dates; committed rosters are checked for those periods; matchup
  keys are 1 to 7. `test_make_multi_fixtures.py`: the respelling test reads periods 1, 6
  and 7.
- dbt comments named in R6.3. SQL is not touched.

## Test strategy

| Requirement | Test | Catches |
|---|---|---|
| R1.1–R1.3 | pytest on a made-up landing zone: periods (31, 36, 37) come out 1, 6, 7 in rosters, lines, pro schedule; settings say 7; (1, 2) stays 1, 2 | numbering by position again, which would put 04-29 on period 2 and fail the pro-games date test |
| R1.4 | the existing date-check pytest, with a third period | a period drifting from its date |
| R2.2, R2.4 | pytest: with an earlier date holding a lower game id, the two later games are still chosen, the history game is added, the correction is of the first | the earlier day displacing an existing boxscore |
| R3.1 | pytest, one case per condition and message: no earlier start; an earlier start with no outs; no later start; rostered on the later day | a fixture that regenerates cleanly and has an empty pool again |
| R3.2, R6.2 | pytest of the committed files | a hand edit, or a regeneration from a changed landing zone |
| R4.1, R4.2, R4.4 | `git status --short fixtures` and `git diff --stat` in the build | an unrelated fixture changing |
| R4.5 | the privacy test, unchanged | member data |
| R5.1–R5.3 | the CI `dbt build`; queries of `ci.duckdb` | the pool still empty; a new warning |
| R5.4 | the isolation gate | a tenant's rows depending on another's |
| Expected values | the last task | numbers that moved since the spike |

## Risks

- The landing zone changes between spike and build and another fixture moves — low;
  nothing is being fetched — R4.4 stops the build.
- A reviewer cannot read a diff of this size — certain — the build reports it as file
  counts and generator output; the payload diffs are generator-made and the pytest pin
  their shape.
- Something reads "fixture period 2" by number and now finds no roster — low — the
  spike's full pytest run found three tests and the CI build none.
- Fixtures grow by about 1.0 MB — certain — accepted by the owner on 2026-10-09 with
  the roster on the earlier day.

## Open questions

- **`rec_fantasy__category_wins_added` stays empty in CI.** #93 lists "cannot re-score a
  pair with a start" among the effects. The model is empty in CI before and after,
  because no fixture matchup is re-scorable: the fixture has 3 of 38 boxscores. Filling
  it needs every game of a matchup's days, which is a different and much larger fixture.
  The owner decided on 2026-10-09: out of scope, and no issue is filed; the
  real-season build exercises the model.
- **Period 1's roster has game lines on 285 of 308 entries** (period 6: all 307; period
  7: 178 of 306). Not looked into, as in spec 0074; the model keeps only lines with
  stats and the tests pass on all three.
- **The R3.1 check treats a pitcher with no id-map row as unrostered.** That matches the
  model today. If #92 or another change resolves players differently, the check should
  follow.

## Review log

| Source | Finding | Resolution |
|---|---|---|
| design-review | F1 (P1): the purpose check proves two starts and an unrostered day, not the model's `SP` role; and R5.1 is held in CI only by a warning | Changed in part: R3.1(a) now requires outs and no more plate appearances than batters faced in the earlier start, which is the role rule for one appearance. Not changed: no hard CI assertion is added. It would be a test that fails on fixtures and warns on real data, which the owner declined for a similar test on 2026-10-07 (spec 0074), and test SQL is a no-go here. The owner confirmed on 2026-10-09: the generator check, the pytest and the existing warning are enough |
| design-review | F2 (P2): R1.2 said the offset applies to matchups, whose keys are trimmed, not mapped | Changed: R1.2 and R1.3 |
| design-review | F3 (P2): the tasks named two cases for R3.1's three conditions | Changed: R6.1, task 3 and the test strategy name one case per condition, by message |
| owner, 2026-10-09 | The five- or six-day gap between a starter's turns is how a rotation works, not a finding about the fixture dates | Changed: the problem statement and ADR 0030 state it as the constraint. The alternative of moving the fixtures to three consecutive days around a short-rest start is removed as never real. A wrong figure is corrected: "13 starts of 3,478" counted only gaps of six days or fewer in its denominator |
| design-review | F4 (P3): `stg_espn__every_scoring_period_has_one_matchup.sql` also describes a two-period fixture | Changed: added to R6.3 |

## Amendments
