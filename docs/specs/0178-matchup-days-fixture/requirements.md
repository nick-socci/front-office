# The CI fixtures carry ESPN matchup-days captures of their own matchups — requirements

Issue: #178 · Tier: M (confirmed by the owner, 2026-10-23) · Status: draft

## Problem

`fixtures/landing/espn/` has no `matchup_days` endpoint, because `scripts/make_fixtures.py`
builds none. So in the CI warehouse `stg_espn__matchup_days` and
`stg_espn__matchup_player_lines` have no rows (design.md, C1). The 17 generic tests on
those two relations (C9) and the six singular tests that read them (C12) pass in CI
without reading a row. `_empty_in_ci.yml` exempts both relations, with a link to this
issue (spec 0174, ADR 0088). The tenant-isolation gate never sees a row of either model.
Their only checks are unit tests and the real-season build. That leaves a gap: a change
to the capture view, `fo_espn_latest`, `fo_unnest` or the last-period choice could break
these models on real input while every gate stays green.

The real data can fill this gap without rewriting anything ESPN sent. The fixture's two
matchups are real matchups of 2026 matchup period 1 (C2). ESPN's own captures for real
scoring periods 1, 6 and 7, which are the fixture's three days of data, mark that matchup
period and carry those two matchups' lines (C3, C4).

## Goals

- In CI, the two relations hold real ESPN rows, so their generic and singular tests and
  the tenant-isolation gate check something on every run.
- The fixture's matchup lines and its matchup totals describe the same real matchups, so
  the reconciliation's lines column is consistent in CI (C8).
- No ESPN value is rewritten. The only changes are the ones every ESPN fixture already
  makes: an allowlist, the fixture league id, and the cut to two matchups.
- Rule 2 holds: the new files carry no member data, and an allowlist test holds them to
  that.

## No-gos

Work that drifts into any of these is escalated, not done.

- No model or test SQL changes. The only edits under `dbt/` are comments, YAML
  descriptions and the two `_empty_in_ci.yml` entries that this work removes.
- No 2025 `matchup_days` fixture. Spec 0085 R3.1 fixes the 2025 fixture season at four
  captures, and that season's day-to-matchup mapping comes from `pointsByScoringPeriod`
  (C14). A 2025 capture would exercise no code path that the 2026 captures don't already.
- No synthetic case in the fixture: no projection line (`statSourceId` 1) and no bye. The
  real captures have neither (C4), and unit tests hold both. They do hold one case that
  `stg_espn__matchup_player_lines` must handle: the string `"Infinity"` as a K/BB value,
  on 5 lines. The model leaves those values out (spec 0147, R1.5), and the fixture keeps
  them as ESPN sent them.
- The marker fallback of `int_fantasy__matchup_periods` (`from_marker`) still gets no CI
  row. 2026 lists every fixture day in `pointsByScoringPeriod` (C6), and getting a row
  there would mean rewriting the matchups fixture. It stays covered by its unit tests.
- No new plants. The singular tests now read rows. Whether they also need plants that
  show them failing is a separate question, and is not this issue's.
- BigQuery is not touched. The fixture feeds only the DuckDB CI build. It holds only fields
  that the capture view declares (`stg_raw__espn_matchup_days`), so nothing in it is
  specific to DuckDB.

## Rabbit holes

- **Which real days to take.** The fixture's rosters come from real scoring periods 31, 36
  and 37, renumbered 1, 6 and 7, but its matchups come from real matchup period 1 (C2).
  The real captures of 31, 36 and 37 mark matchup periods 4 and 5, and carry no lines for
  the fixture's matchups (C3). → The captures follow the matchups, not the rosters: real
  scoring periods 1, 6 and 7, whose numbers need no renumbering.
- **The multi-league fixture.** `make_multi_fixtures.py` copies every 2026 ESPN capture
  into its one-period 2027 seasons. Copied as it stands, it gives 2027 the markers of
  periods 6 and 7, which 2027 does not have, and
  `int_fantasy__matchup_periods_use_their_own_scoring_periods` fails on 4 rows (C10). →
  2027 keeps the period-1 capture only, as it already does for rosters.
- **The empty-endpoint branch of `duckdb__fo_captures`.** Once every capture view's
  endpoint has fixture captures, the CI build stops exercising that branch (C15). → A
  pytest already holds it on a temporary landing zone
  (`test_an_endpoint_with_no_captures_gives_no_rows_and_its_columns`). Only the comment
  in `json.sql` changes.
- **Size.** Each projected capture is 116,550 bytes (C5). → Three captures, not seven.
  Within the multi-league fixture, the 2027 seasons get one capture each.

## Requirements

### R1. The fixture captures

`make_fixtures.py` builds the captures from the real landing zone, from an allowlist, the
same way it builds every other ESPN fixture.

- R1.1 THE SYSTEM SHALL write one `espn/matchup_days` capture of the fixture league for
  each fixture scoring period of 2026 that has roster data (1, 6 and 7). Each capture is
  built from the newest committed real capture of the 2026 scoring period with the same
  number.
- R1.2 THE SYSTEM SHALL keep in each capture only the matchups that the matchups fixture
  keeps: the first `FIXTURE_MATCHUPS` of the schedule.
- R1.3 THE SYSTEM SHALL rebuild each capture from an allowlist and copy nothing else:
  - the top-level `id` (set to the fixture league id), `seasonId` and `scoringPeriodId`;
  - per matchup, `id` and `matchupPeriodId`;
  - per side, `teamId`; the marker `rosterForCurrentScoringPeriod`, as an empty object;
    and `rosterForMatchupPeriod.entries[]`, with each entry's `playerId` and, for each
    of its stat lines, `statSourceId`, `statSplitTypeId`, `scoringPeriodId` and `stats`
    (copied whole: stat ids to numbers).
- R1.4 IF a real side has no marker, or no `rosterForMatchupPeriod`, THEN THE SYSTEM SHALL
  leave that key out of the fixture side and invent nothing.
- R1.5 THE SYSTEM SHALL write each capture's sidecar with the partitions `season`,
  `league_id` (the fixture league) and `scoring_period`, the params
  `view=mMatchupScore,mScoreboard` and `scoringPeriodId`, and the stamp
  `FIXTURE_FETCHED_AT`.
- R1.6 IF a wanted scoring period has no committed real capture THEN THE SYSTEM SHALL stop
  before writing any fixture, and name the period.
- R1.7 IF the kept matchups of a capture differ from the matchups fixture's in matchup id
  or team ids THEN THE SYSTEM SHALL stop before writing any fixture, and name the capture.

### R2. Privacy

- R2.1 THE SYSTEM SHALL keep every new payload and sidecar free of the forbidden keys and
  the GUID pattern of `front_office/privacy.py`. The existing privacy tests cover these
  files with no change, because they scan every file under `espn/` in both fixture roots.
- R2.2 THE SYSTEM SHALL fail a pytest if a committed `matchup_days` fixture holds a leaf
  path outside the R1.3 allowlist, or a league id other than the fixture's.

### R3. The CI warehouse

- R3.1 WHEN the gates build the fixture warehouse, THE SYSTEM SHALL give
  `stg_espn__matchup_days` and `stg_espn__matchup_player_lines` the rows listed under
  *Expected values*.
- R3.2 WHEN the gates build the fixture warehouse, THE SYSTEM SHALL leave every other
  relation unchanged, except `raw.captures`, `stg_raw__espn_matchup_days` and the
  `matchup_line_value` column of `rec_espn__matchup_stat_differences`.
- R3.3 THE SYSTEM SHALL drop the two `#178` entries from `dbt/plants/_empty_in_ci.yml`,
  and the plant gate SHALL pass.
- R3.4 THE SYSTEM SHALL correct every comment and YAML description that says CI holds no
  matchup-days capture (design.md, *Detailed design* lists them).
- R3.5 THE SYSTEM SHALL update `test_the_2026_fixture_season_is_untouched_by_the_past_season`
  so that the set it pins includes `("espn", "matchup_days")`.
- R3.6 IF, for a count stat of a fixture side, the sum of that side's numeric period
  lines in the period-7 capture differs from the side's `scoreByStat` score in the matchups
  fixture THEN THE SYSTEM SHALL fail a pytest of the committed files. A count stat is a
  stat of `espn_stat_components.csv` with no denominator part, as
  `rec_espn__matchup_line_totals` defines it. A stat absent from the lines counts as 0.
  This holds the fixture's two records of a matchup to each other across regenerations
  (C8, C16).

### R4. The multi-league fixture

- R4.1 WHEN `make_multi_fixtures.py` builds the 2026 seasons of both leagues, THE SYSTEM
  SHALL carry the three captures into each, relabelled as every other capture is.
- R4.2 WHEN it builds a one-period 2027 season, THE SYSTEM SHALL keep only the
  `matchup_days` capture of scoring period 1, as it does for rosters.
- R4.3 THE SYSTEM SHALL fail a pytest of the committed multi tree if a 2027 league holds a
  `matchup_days` capture of any period other than 1.
- R4.4 WHEN the gates run tenant isolation, THE SYSTEM SHALL report 0 differing
  relation/league-season pairs.

### R5. The real season

- R5.1 THE SYSTEM SHALL leave the real-season warehouse identical: the SQL that dbt
  compiles for every model and test, with comments stripped, is the same on the branch
  as on `main`.

## Expected values

Measured on a prototype (design.md, C6 to C10). Each row is checked by a test or a query.

| Check | Expected | How to verify |
|---|---|---|
| `stg_espn__matchup_days` in CI | 3 rows: league 111111, 2026, scoring periods 1, 6 and 7, all matchup period 1 | `select * from staging.stg_espn__matchup_days` |
| `stg_espn__matchup_player_lines` in CI | 3,798 rows (3,803 stat values less the 5 `"Infinity"` K/BB values); 4 sides (matchup 1: teams 9 and 6; matchup 2: teams 2 and 3); 25, 22, 23 and 17 players; 82 stat ids per side; scoring period 7 on every row | group by matchup, team |
| `rec_espn__matchup_stat_differences` in CI | 96 rows, all `unverified`, as on `main`; `matchup_line_value` set on the 80 count rows and equal to `espn_value` on all 80 | C8's query; the R3.6 pytest (21 count stats, 80 side-stats equal) |
| Every other CI relation | unchanged from `main` | relation diff (C6's script) |
| `dbt build` on the fixtures | PASS 776, WARN 3, ERROR 0, the same as `main` | gates |
| Plant gate | passes; generic tests reading zero CI rows go from 35 to 18; 37 plants run | `scripts/check_plants.py` |
| Multi tree, `stg_espn__matchup_days` rows per league-season | 3, 3, 1, 1 (2026 ×2, 2027 ×2) | query on the multi build |
| Tenant isolation | 0 differing pairs | gates |
| Fixture size | `fixtures/landing` +349,650 bytes (3 × 116,550); `fixtures/landing_multi` +932,400 bytes (8 × 116,550) | `du -b` |
| Real-season warehouse | compiled SQL identical to `main` once comments are stripped; the two models' real row counts unchanged, and their tests pass | tasks.md, task 10 |
