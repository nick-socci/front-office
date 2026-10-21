# 0089. The id-map coverage test fails on a league-season's share of uncovered started players

- Status: proposed
- Date: 2026-10-20
- Spec: [0177-idmap-coverage-per-league-season](../specs/0177-idmap-coverage-per-league-season/design.md) · Issue: #177

## Context

`stg_idmap__covers_started_players` counts the distinct started players with no SFBB
crosswalk row, across every loaded season, and errors above 25. The threshold dates from a
2026-only warehouse (9 players). With eight seasons loaded it returns 24 (spec 0177, C1),
so loading a season moves it toward failing with nothing wrong with the map.

Per league-season, the uncovered share is at most 1.87% (C2). Every uncovered player
resolves through the unambiguous-name fallback (C3). Most of the gap is SFBB rows with a
blank ESPN id, not late call-ups (C4). The fallback alone would resolve 97–99.8% of
started players with no map at all (C6). So a test of unresolved players cannot see the
map break. This test is the only one that can.

## Decision drivers

- It must still fail when the map breaks (the issue's condition).
- Loading another league-season must not move it toward failing.
- One rule for any league, whatever its size.
- No warning that fires on every build.

## Considered options

What it checks:
1. **The crosswalk's coverage of started players.**
2. **Players left unresolved after the name fallback.**

How it counts:
3. **Share per league-season.**
4. **Count per league-season.**
5. **Share pooled across the warehouse.**
6. **A check on the map alone** (its row count).

The limit: **3%**, **5%** or **10%** of a league-season's started players.

Below the limit: **(a)** no warning, **(b)** warn on any uncovered player, **(c)** warn
above a lower share.

## Decision

Chosen by the owner on 2026-10-20, one at a time in this order: **1** (what it checks), **3**
(how it counts), **5%** (the limit), **(a)** (below the limit). The test fails, with one row
per league-season, when `100 * uncovered_players > 5 * started_players`, and is silent
otherwise.

- **1 over 2:** option 2 duplicates `dim_player_league_seasons_rostered_players_are_resolved`.
  The fallback also hides a broken map from it.
- **3 over 4:** a count fits one league's size. **3 over 5:** a pooled share lets healthy
  seasons dilute a broken one. **3 over 6:** a map with plenty of rows can still miss this
  league's players.
- **5% over 3%:** 3% leaves 1.6× headroom, and one ordinary bad season (15 of 481) would
  fail the build. The gap below the limit persists after a season ends rather than closing
  (players of 2022–2025 still have blank ESPN ids in a 2026 map, C4), and it has grown from
  0.22% to 1.87% (C2), so the limit needs headroom. **5% over 10%:** 10% could pass a map frozen a season earlier, which a
  debut-based proxy puts at 7–13% (C8, a proxy, not a bound).
- **(a) over (b):** (b) warns on 5 of 8 league-seasons on every build. The name-matched
  players are marked by `player_resolution`, and the resolution test warns on any it cannot
  match. **(a) over (c):** (c)'s second threshold has no evidence behind it.

## Consequences

- Good: the result for a league-season depends only on that league-season. The ninth
  season cannot fail the eighth's build.
- Good: an empty map, a renamed or emptied id column, or a map missing more than a
  twentieth of a league-season's started players fails the build. Plants show it on every
  CI run, including beside a healthy league-season.
- Bad / accepted cost: map rows of players this league never started (2,424 of 3,657, C13)
  can be lost unseen. Nothing here reads them.
- Bad / accepted cost: a map that drifts slowly, under 5% a season, is not reported by this
  test. The players it misses still show as `unambiguous_name`, or warn as `unresolved`.
- Bad / accepted cost: where a frozen map falls is unknown (C8 is a proxy), so it may stay
  under 5%. An early-season map may also cross 5% and fail a build on a gap SFBB later
  closes.
- Follow-ups: revisit the limit when a second league is loaded, or when dated map captures
  show the in-season lag.
