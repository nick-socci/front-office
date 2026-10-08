# Past seasons' matchup totals, in a build that can hold a season with no rosters — requirements

Issue: #85 · Tier: L · Status: draft

## Problem

#57 wants to measure how far apart two teams finish in each category, over several
seasons, and to replace ADR 0010's scale only if that shows it is wrong. ADR 0010's own
cost section says its scale rests on 143 matchups of one season. A probe on 2026-10-08
showed that ESPN still serves per-category matchup totals for 2018, 2021 and 2025, in the
shape of 2026: about 143 to 149 two-sided matchups a season, so roughly 1,150 for 2018 to
2025.

Two things stand in the way of landing them.

Nothing can fetch a season's settings and matchups alone. `backfill espn` fetches a whole
season: about 180 roster periods as well, which a past season does not need here.

And the build assumes that a league-season with matchups has rosters and boxscores too.
Spikes on 2026-10-08, on made-up seasons in a scratch copy of the fixtures, showed what
fails for a season holding only settings and matchups: null scoring dates until its pro
schedule is loaded; the opening-day test until MLB's schedule is; then four mart tests,
because the value marts build for every league-season that has matchups; and, for a
season shaped like 2018 to 2021, the relationship from scored categories to stat
components (complete games has no rule) and the test that every scoring period belongs
to a matchup (2021's matchups have no per-day breakdown).

This spec is the first half of #57: land the totals and make the build right for such a
season. Measuring the margins is #57 itself, specced afterwards against what is landed.

## Goals

- The matchup totals of 2018 to 2025 are landed and staged, with what dates their
  scoring periods.
- A league-season with no rosters builds and tests clean, and no value is computed for
  it.
- Which league-seasons have rosters is stated once, in data, and every model and test
  that needs it reads it from there.
- Nothing about the 2026 season changes.
- CI builds a season with no rosters on every run.

## No-gos

- **No measuring of margins, no new scale, no change to ADR 0010.** That is #57.
- **No rosters, teams, transactions or boxscores for past seasons** (#83 proposes them).
- **No season before 2018.** They are believed to sit behind another endpoint.
- **No component rule for complete games**, and no new MLB stat staged for it.
- **No clean audit for a season with no rosters.** `front-office audit --season <past>`
  is not changed to understand one; see *Open questions*. Only its help text changes
  (R1.5).
- **No change to the grain, name or columns of any existing model.**
- **No invented fixture data.** The past season in the fixtures is real data cut down.

## Rabbit holes

- *A list of covered seasons in a seed or a variable* → coverage is read from what is
  loaded: a league-season is covered when it has roster entries.
- *Making every existing test pass for every season* → a test about values we compute
  applies to covered league-seasons; a test about what ESPN reported applies to all. No
  test is loosened for a covered season.
- *Why 2021 has no per-day breakdown* → not chased. Nothing needs it for a season with no
  rosters.
- *The shortened 2020 season* → landed like the others; whether its matchups are usable
  is #57's question. *Amended 2026-10-08:* it has none. The league did not play in 2020
  (R5.5).
- *Teams for past seasons, to name the sides* → not landed. A side is a team id.

## Requirements

### R1. Fetch a season's matchup totals alone

- R1.1 WHEN `front-office backfill espn --season <year> --only matchups` runs THE SYSTEM
  SHALL land, under the run's one stamp, the pro schedule with the public client, then
  the league's settings and matchups with the authenticated client, and nothing else.
- R1.2 THE SYSTEM SHALL land them as the same endpoints, partitions and request records
  as a full run does, so that staging reads them unchanged.
- R1.3 IF the pro schedule fails in that run THEN THE SYSTEM SHALL report it, still
  land settings and matchups, and exit non-zero (spec 0073, R1.7).
- R1.4 THE SYSTEM SHALL leave a full `backfill espn` run, and `--only pro-schedule`, as
  they are.
- R1.5 THE SYSTEM SHALL say in the help of `front-office audit` that it judges a season
  landed whole, and reports a season landed with `--only matchups` as missing its
  rosters and boxscores. No finding of the audit changes.

### R2. Season coverage

- R2.1 THE SYSTEM SHALL provide `int_fantasy__league_seasons` with one row per
  (`platform`, `league_id`, `season`) that has league settings loaded, and a boolean
  `has_rosters`: true when the league-season has at least one roster entry.
- R2.2 THE SYSTEM SHALL compute matchup side totals, stat values, matchup category
  scores, matchup results, category scales, player values and transaction impact only
  for league-seasons with `has_rosters`.
- R2.3 THE SYSTEM SHALL compare our values with ESPN's, in the reconciliation models and
  tests, only for league-seasons with `has_rosters`.
- R2.4 THE SYSTEM SHALL keep staging models, `int_fantasy__categories`,
  `int_fantasy__matchup_sides` and `stg_espn__scoring_periods` building for every
  league-season loaded.
- R2.5 THE SYSTEM SHALL apply to covered league-seasons only: the relationship from a
  scored category to a stat component rule, and the test that every scoring period
  belongs to exactly one matchup period. Both keep their full strength for a covered
  league-season.
- R2.6 THE SYSTEM SHALL fail the build if a league-season has roster entries and no
  matchups, or roster entries and no settings: coverage does not excuse a half-landed
  season.
- R2.7 THE SYSTEM SHALL NOT change a row of any model for the 2026 league-season.

### R3. A past season in the fixtures

- R3.1 THE SYSTEM SHALL add to `fixtures/landing/` the 2025 season of the fixture
  league, holding settings, matchups, ESPN's pro schedule and MLB's schedule, and no
  roster, team, transaction or boxscore, generated by `scripts/make_fixtures.py` from
  the landed 2025 captures by the allowlists the 2026 fixtures use.
- R3.2 THE SYSTEM SHALL build it as a two-period season: real scoring periods 1 and 2 of
  2025, with MLB's games of their two dates, and generation SHALL fail unless those
  periods fall on those dates in ESPN's schedule (ADR 0025).
- R3.3 THE SYSTEM SHALL keep the 2026 fixtures byte for byte.
- R3.4 THE SYSTEM SHALL carry the 2025 season into `fixtures/landing_multi/` for the
  base league, and SHALL have the tenant-isolation check build it alone as a fifth
  league-season, staying at 0 differing pairs.
- R3.5 THE SYSTEM SHALL keep the fixture privacy test passing with its patterns
  unchanged.

### R4. Tests

- R4.1 THE SYSTEM SHALL test `--only matchups` with a fake transport: what is requested
  and in what order, with and without cookies; that no roster, team or transaction
  request is made; the failure path of R1.3; that an unknown `--only` value is refused.
- R4.2 THE SYSTEM SHALL have dbt unit tests for `int_fantasy__league_seasons`: a season
  with rosters is covered; one with settings and matchups only is not; two leagues and
  two seasons stay apart.
- R4.3 THE SYSTEM SHALL have a dbt test that no value mart holds a row for a league-season
  without rosters, and one for R2.6.
- R4.4 THE SYSTEM SHALL have the made-up cases of the spikes covered in CI by the 2025
  fixture season: no rosters, and whatever real 2025 holds.

### R5. The landed seasons

- R5.1 WHEN the build lands 2018 to 2025 THE SYSTEM SHALL have, for each season: one
  settings capture, one matchups capture and one pro schedule capture of the league,
  and one MLB schedule capture.
- R5.2 THE SYSTEM SHALL build and test clean on the real warehouse with all nine seasons
  loaded.
- R5.3 IF a season fails a test that this spec does not restrict to covered seasons THEN
  the build SHALL stop and take it to the owner, with the season, the test and the rows.
- R5.4 THE SYSTEM SHALL fail the build for every decided matchup (a winner other than
  `UNDECIDED`) that lacks a reported score, on either side, for a category its
  league-season scores. A matchup not yet decided, and a bye, are not held to it.
- R5.5 WHEN the past seasons are landed THE SYSTEM SHALL have, for each of 2018 to 2025
  that the league played, at least one decided two-sided matchup; IF a season has none
  THEN the build SHALL stop and take it to the owner. A capture that parses to no
  matchups is not a landed season. The count is made per season when the seasons are
  landed and recorded in the run evidence; it is not a dbt test, because a season that
  was not played and a capture that parsed to nothing look the same in staging.
  *Amended 2026-10-08:* the build stopped here for 2020. ESPN's response holds no
  matchup because the league did not play; the owner chose to keep 2020 loaded with
  settings and no matchups. The requirement holds for the other seven seasons (design.md,
  *Amendments*).
- R5.6 WHEN the build stops under R5.3 or R5.5 THE SYSTEM SHALL first have landed and
  built every season it can, so that every season with a problem is reported to the
  owner together. It SHALL NOT exclude a season, or narrow a test, to get past one.

## Expected values

Known on 2026-10-08, from the #57 probe (2018, 2021, 2025), the #73 check of ESPN's
schedules (2018, 2024, 2025) and the real warehouse (2026). Seasons not probed have no
expected value: the build records what it finds.

| Check | Expected | How to verify |
|---|---|---|
| Every row of every model, 2026 league-season | identical before and after | `EXCEPT ALL` both ways against a copy, restricted to season 2026 |
| League-seasons in `stg_espn__league_settings` | 9: 2018 to 2026 | query |
| `int_fantasy__league_seasons` | 9 rows; `has_rosters` true for 2026 only | query |
| Rows in the value marts for 2018 to 2025 | 0 | R4.3's test |
| Decided two-sided matchups, each with a score for every scored category on both sides | 2025: 149 · 2021: 143 · 2018: 143 · 2026: 143 · the other five seasons: at least one, the number recorded. *As landed:* 2019: 143 · 2022: 143 · 2023: 143 · 2024: 155 · 2020: none, not played (amendment) | R5.4's test; R5.5's count per season |
| Schedule entries / two-sided matchups | 2025: 151 / 149 · 2021: 145 / 143 · 2018: 145 / 143 · 2026: 145 / 143 | `stg_espn__matchups` |
| Scored categories | 2025: 17, the 2026 list · 2021 and 2018: 18, with SV and CG and without SVHD | `int_fantasy__categories` |
| Final scoring period | 2025: 188 · 2021: 179 · 2018: 179 | `stg_espn__league_settings`; `stg_espn__scoring_periods` row counts |
| Period 1 per ESPN's schedule | 2025: 2025-03-18 · 2024: 2024-03-20 · 2018: 2018-03-29 | `stg_espn__scoring_periods` |
| Games in every season on one date per period | 0 rows from the one-date test | `dbt build` |
| MLB opening day equals period 1 | 2018: expected. 2024 and 2025: **not known**: it holds only if MLB files the Seoul and Tokyo openers as regular season | `stg_espn__scoring_periods_start_on_opening_day`; a failure is R5.3 |
| `stg_espn__matchup_periods` for 2021 | no rows: its matchups have no per-day breakdown | query |
| Real build | passes; the one warning it has today, unchanged | `dbt build` |
| CI | passes with the 2025 season in it; warnings unchanged at 3 | `dbt build --target ci` |
| Tenant isolation | 0 differing pairs over 5 league-seasons | `.agentic/gates` |
| Requests made | 16 authenticated (settings and matchups, 8 seasons); 16 public (pro schedule and MLB schedule, 8 seasons) | the run's output |
