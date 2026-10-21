# The id-map coverage test judges each league-season by its share of started players — requirements

Issue: #177 · Tier: M · Status: proposed

## Problem

`stg_idmap__covers_started_players` lists the distinct players who were started (not on
BE or IL) and have no row in the SFBB crosswalk. It warns above 0 and **errors above 25**.
It counts across every loaded season, but its threshold was set when only 2026 was loaded,
at 9 players. On the eight-season warehouse it returns 24 (design.md, C1), one player short
of failing. Loading another season adds that season's gap to the same count (C2), so the
build would fail with no change to the map.

No value is lost today. Each of the 24 resolves through the unambiguous-name fallback, and
no started day is unresolved (C3). The test does have a job, though: it is the only test
that sees the map break. With no map at all, the name fallback alone would still resolve
97–99.8% of each season's started players (C6), so a test of what is left unresolved would
barely move.

## Goals

- Loading another league-season cannot by itself move the test toward failing.
- The test still fails when the map itself breaks: it is empty, an id column is renamed or
  emptied, or it loses the rows of a large part of the players this league starts.
- The same rule fits any league, whatever its size.
- What the test means is written in its header and is true of the data: the gap is mostly
  map rows with a blank ESPN id, not only late call-ups (C4).

## No-gos

- Raising the threshold of the count across seasons. The issue rules it out: the next
  season would cross any fixed count.
- Changing the crosswalk or the name fallback (`int_fantasy__player_crosswalk`), or adding
  hand-made map rows for the 24 players. Reporting the blank ESPN ids to SFBB is not this
  work either.
- Changing `dim_player_league_seasons_rostered_players_are_resolved`, the test of players
  left unresolved after the fallback.
- Detecting wrong mappings, where the map pairs an ESPN id with the wrong MLBAM id. A
  coverage count cannot see those.
- Changing the idmap freshness check (`_raw_feeds__sources.yml`: warn after 14 days).

## Rabbit holes

- Measuring the in-season lag of the map. That needs map captures from earlier in a
  season, and the landing zone holds one (C5). → The threshold rests on the end-of-season
  shares (C2) and on a debut-based proxy for a stale map (C8). The possible early-season
  failure is a recorded risk. The lag is an open question,
  not a task.
- Choosing the threshold by simulating every way the map could break. → Prototype the
  failures named in the goals (C6, C8) and leave headroom over the worst real share (C2).
- Weighting by started days instead of players. → Players are what the map lists, so
  coverage is counted in players. Days measure value impact, which the resolution test
  already covers.

## Requirements

### R1. What the test counts

The test measures the crosswalk's coverage of started players, one league-season at a time.

- R1.1 THE SYSTEM SHALL count, for each (`league_id`, `season`) of
  `stg_espn__roster_entries`, the distinct `espn_player_id`s that held a scoring slot
  (`espn_lineup_slots.is_starting_slot`) on at least one roster entry, and how many of
  those have no row in `stg_idmap__players`.
- R1.2 THE SYSTEM SHALL compare the two counts as integers
  (`100 * uncovered_players > 5 * started_players`), with no division and no floating
  point.
- R1.3 THE SYSTEM SHALL give each league-season the same result whether it is built alone
  or with other league-seasons.

### R2. When it fails

- R2.1 IF a league-season's uncovered players are more than 5% of its started players THEN
  THE SYSTEM SHALL fail the build with severity `error`, returning one row per such
  league-season with `league_id`, `season`, `started_players` and `uncovered_players`.
- R2.2 WHILE every league-season is at or below 5% THE SYSTEM SHALL pass the test with no
  warning.
- R2.3 THE SYSTEM SHALL state in the test's header comment what it guards (the map, not
  value resolution), the threshold and why it was chosen, the shares on the real season,
  and the three ways the current gap arises (C4).

### R3. It is shown to fail

The CI fixtures hold no uncovered started player (C9), so the failing case is planted
(spec 0174).

- R3.1 THE SYSTEM SHALL hold a plant file `dbt/plants/stg_idmap__covers_started_players.yml`
  that removes the crosswalk rows of more than 5% of the fixture's started players, and
  expects `{status: fail, failures: 1}`.
- R3.2 The plant file SHALL also remove the rows of exactly 5% and expect `pass`, so the
  boundary is held.
- R3.3 The plant file SHALL also empty the map and expect `{status: fail, failures: 1}`:
  the map broken outright.
- R3.4 The plant file SHALL also add a second league-season whose started players are all
  covered to the over-limit case, and expect `{status: fail, failures: 1}`: a healthy
  league-season does not dilute a failing one (R1.3).

### R4. It stays portable

The test is in the BigQuery slice (C10).

- R4.1 THE SYSTEM SHALL write the test in SQL that DuckDB and BigQuery both accept, so
  that `test_dbt_portable_sql_rule.py` passes, and the test compiles for the `bq` target.

## Expected values

| Check | Expected | How to verify |
|---|---|---|
| Test result on the eight-season warehouse | `PASS`, 0 rows | `dbt build --select stg_idmap__covers_started_players` (real season) |
| Share per league-season on that warehouse | 2018, 2019, 2021: 0 of 429, 407, 425. 2022: 1 of 454. 2023: 1 of 450. 2024: 8 of 452. 2025: 8 of 479. 2026: 9 of 481 (max 1.87%) | the C2 query |
| CI fixture build | `PASS`, 0 rows; 0 uncovered of 260 started | gates |
| Plants | over the limit: `fail 1`; at the limit: `pass`; empty map: `fail 1`; over the limit beside a healthy league-season: `fail 1` | `scripts/check_plants.py` in the gates |
| Warnings on the real build | one fewer than before: this test no longer warns | `dbt build` summary, before and after |
