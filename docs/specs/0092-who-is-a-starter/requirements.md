# Who is a starter, for call-ups and pitchers who change role — requirements

Issue: #92 · Tier: M · Status: approved 2026-10-09

## Problem

The start replacement level is the average of every free-agent start by a pitcher who
was "a starter at the time" (ADR 0029). Today that means: on his MLB appearances of the
season before that date, at least half were starts (`fo_replacement_group` says `SP`).
The owner accepted the rule on 2026-10-09 "for now" and asked for a better answer in two
places.

Measured on 2026, read-only, on the real warehouse (2026-10-09). There were 1,875
free-agent starts on the league's scoring dates, by 282 pitchers. The rule takes 1,290
and leaves out 585, which fall into four kinds:

| Left out today | Starts | Pitchers | Outs a start | ERA | Faced 9 or fewer |
|---|---|---|---|---|---|
| No earlier pitching appearance this season | 120 | 120 | 13.68 | 4.55 | 3 (2.5%) |
| A reliever by the count, whose last two appearances were both starts | 108 | 24 | 14.31 | 5.10 | 3 (2.8%) |
| A reliever by the count, last appearance a start, the one before not | 66 | 53 | 10.95 | 4.71 | 18 (27%) |
| A reliever by the count, last appearance in relief | 291 | 153 | 7.21 | 4.39 | 177 (61%) |

"Faced 9 or fewer" (once through the order) is used here only to describe a group: it
is what an opener's day looks like. It is never a condition of the rule (see *No-gos*).

- **The first row is the call-up problem, and more.** 67 of the 120 fall in the
  season's first fortnight: they are every rotation's first turn, not call-ups. In those
  14 days the pool holds 46 starts of 122.
- **The second row is the role-change problem.** A pitcher who relieved early and then
  joined a rotation stays a "reliever" until his starts outnumber his relief outings.
  Twenty-four pitchers lose up to 11 starts each this way.
- **The fourth row is what the rule is for.** Most of it is openers, and it should stay
  out. The 114 full-length starts inside it are a reliever's first start: nothing known
  before the game tells it from an opener's.

The level hardly depends on any of this (ERA 4.82 to 4.93 across every version tried),
so this is about the definition being right, as the issue says.

Two of the issue's ideas cannot be done with what is landed. Only the 2026 MLB season is
in the warehouse, so there is no previous season or minor-league record to carry a role
from. And ESPN's position eligibility arrives in roster payloads, which hold rostered
players only: a free agent is by definition not in one. The third-party id map labels
every one of these pitchers `P`.

## Goals

- A pitcher making his first appearance of a season as a starter counts as one.
- A pitcher who has joined a rotation counts as a starter after two turns, not after his
  starts outnumber his earlier relief outings.
- Openers stay out, to the extent anything known before the game allows.
- No hindsight, nothing from the outing itself, no parameter fitted to this league.
- Nothing but the start replacement level, and the values measured against it, moves.

## No-gos

- **No condition on the outing itself** (length, batters faced, pitches). A start cut
  short is a bad start, and the pool must keep it: the 18 starts in today's pool that
  faced 9 or fewer run at a 16.55 ERA, and dropping them moves the level from 4.90 to
  4.87 by selecting on the result.
- **No change to `fo_replacement_group`**, so none to `dim_players`,
  `dim_player_league_seasons`, the batting pool or the relief pool.
- **No new data source**: no previous season, no minor leagues, no new ESPN view.
- **No change to how a pitcher's own day is valued**: a start is still measured against
  the start level whoever threw it (ADR 0008).
- **No change to the fixture generator's purpose check** (spec 0093, R3.1).
- **No output column added to or removed from any model.**

## Rabbit holes

- *Telling a reliever's first real start from an opener's before the game* → not
  possible from appearances. Both stay out; 114 full-length starts are the cost,
  accepted by the owner on 2026-10-09.
- *A window of recent appearances with a size to choose* → measured (2 of the last 3:
  1,488 starts) and not chosen: it adds a parameter and lets 11 starts in straight from
  relief.
- *Weighting recent appearances* → the same, with a decay rate to choose.
- *Recomputing every player's value by hand to predict the movement* → the level moves
  by 0.14 outs and 0.01 of ERA; the build records the movement and stops on a surprise
  (R5.3).

## Requirements

### R1. A starter at the time

For a free-agent start on a league-season's scoring date, the pitcher's *earlier pitching
days* are his MLB days of the same season, strictly before that date, on which he
pitched. A pitching day is a start or relief by `fo_pitching_day_kind`.

- R1.1 WHEN the pitcher has no earlier pitching day THE SYSTEM SHALL put the start in
  the pool.
- R1.2 WHEN `fo_replacement_group` over all his earlier MLB days says `SP` THE SYSTEM
  SHALL put the start in the pool, as today.
- R1.3 WHEN his two most recent earlier pitching days were both starts THE SYSTEM SHALL
  put the start in the pool, whatever R1.2 says.
- R1.4 THE SYSTEM SHALL leave every other free-agent start out of the pool.
- R1.5 THE SYSTEM SHALL decide R1.1 to R1.3 from days before the start only, of the same
  MLB season only, and from all his MLB days, not only his free-agent ones.
- R1.6 THE SYSTEM SHALL keep the pool unranked and without a size, and its level the
  pool's totals over its days (ADR 0029).

### R2. Nothing else moves

- R2.1 THE SYSTEM SHALL leave `fo_replacement_group` and every model that calls it for
  another purpose unchanged in its rows.
- R2.2 THE SYSTEM SHALL leave the batting and relief rows of
  `int_fantasy__replacement_levels` unchanged.

### R3. Tests

A dbt unit test gives a model made-up input rows and asserts its output rows; no
warehouse data is involved.

- R3.1 THE SYSTEM SHALL have dbt unit tests of `int_fantasy__replacement_levels` in
  which: a first appearance of the season that is a start is in the pool; a pitcher who
  relieved three times and then started twice has his third start in the pool and his
  first two out; a pitcher who relieved, started, relieved and starts again is out; an
  opener (relief days only before) is out; a start made in another season does not
  count as an earlier pitching day; a later day never changes an earlier start's
  status; a rostered pitcher's start is out; a player who has batted this season and
  never pitched is in on his first start (R1.1 counts pitching days, not MLB days); a
  day on which he only batted, between two starts, does not break "his last two".
- R3.2 THE SYSTEM SHALL revise every existing unit test of the model whose expectations
  rest on a first start being out, and no other. Known from reading them:
  `…the_start_pool_is_every_free_agent_start_by_a_starter_at_the_time` (first starts
  out; a 2025 starter's first 2026 appearance out),
  `…a_relief_pool_members_start_is_not_in_the_relief_level` (900002's first start out)
  and `…an_empty_pool_still_has_rows_with_a_null_level` (a debut start, and an empty
  start pool). The first two take the new expectations. The third must still show an
  empty start pool with its rows and a null level, so its given rows change: the start
  is by a pitcher who relieved earlier. Each keeps every assertion that is not about a
  first start, and its description is brought up to date. Any further test found
  failing for this reason at task 2 is listed on #92 before it is revised.
- R3.3 THE SYSTEM SHALL keep every other test unchanged and passing, including
  `values_track_rescored_category_wins` and
  `fct_player_category_value_the_replacement_pool_is_worth_zero`.

### R4. The fixtures and CI

Depends on #93's build being merged: its fixtures are the CI baseline.

- R4.1 IF #93's build is not merged THEN the build of this spec SHALL wait.
- R4.2 THE SYSTEM SHALL leave every fixture file unchanged, and both generators
  unchanged in what they do: the one edit is the comment of R6.2. The generator's
  purpose check (spec 0093, R3.1) still means what it says: a pitcher with
  one earlier start, with outs, is a starter under R1.2.
- R4.3 THE SYSTEM SHALL have the CI start pool hold four starts by three pitchers: the
  one admitted by his history (678394 on fixture period 6) and three admitted by R1.1.

### R5. The real season

- R5.1 THE SYSTEM SHALL build and test clean on the real warehouse, with the warnings it
  has today and no new one.
- R5.2 THE SYSTEM SHALL change no model's rows except the start rows of
  `int_fantasy__replacement_levels`; the value columns derived from them in
  `fct_player_category_value`, `fct_player_season_value` and `fct_transaction_impact`;
  and the two models that re-score matchups against the level,
  `rec_fantasy__category_wins_added` and `rec_fantasy__category_wins_by_group`, in
  their measures and not in their row counts.
- R5.3 IF a level or count differs from *Expected values* beyond the rounding shown, a
  model outside R5.2 changes, or `values_track_rescored_category_wins` fails THEN the
  build SHALL stop and take it to the owner, having finished every other check. It SHALL
  NOT change a test, a tolerance or an expected value to get past one.
- R5.4 THE SYSTEM SHALL record, before the PR is opened, how starters' values moved:
  the median and the largest movers of `fct_player_season_value`, and the hitter and
  starter counts of the top 20, against the figures of spec 0089.

### R6. Words

- R6.1 THE SYSTEM SHALL bring the header of `int_fantasy__replacement_levels.sql`, its
  model and unit test descriptions, and the macro's own comment up to date, with the
  2026 figures of this spec.
- R6.2 THE SYSTEM SHALL say in `scripts/make_fixtures.py`, at the purpose check, that
  the check holds the history path of the rule and that a first start is now in the
  pool without it. A comment only.

## Expected values

Measured on 2026-10-09 on the real warehouse, by a query that reproduces today's pool
exactly (1,290 starts, 153 pitchers, 19,251 outs).

**The start level** (`int_fantasy__replacement_levels`, `day_kind = 'start'`):

| | Today | After |
|---|---|---|
| `pool_players` / `pool_played_days` | 153 / 1,290 | 182 / 1,518 |
| `pool_total`, outs / earned runs | 19,251 / 3,496 | 22,438 / 4,065 |
| Outs a start | 14.92 | 14.78 |
| ERA / WHIP | 4.90 / 1.403 | 4.89 / 1.404 |
| Strikeouts / wins a start | 4.091 / 0.252 | 4.086 / 0.249 |
| Starts that faced 9 or fewer | 18 (1.4%) | 24 (1.6%) |
| Pool starts in the season's first 14 days | 46 | 113 |

**Where the 228 added starts come from**: 120 by R1.1 and 108 by R1.3. R1.2 keeps its
1,290. Still out: 357, of which 195 faced 9 or fewer.

**By half of the season** (split at 2026-06-24), ERA: today 4.91 and 4.90 over 617
and 673 starts. After: 4.89 and 4.89 over 734 and 784.

| Check | Expected | How to verify |
|---|---|---|
| Batting and relief rows of the levels | identical to today | `scripts/compare_warehouses.py` or a row diff |
| Models outside R5.2 | no row changes | the same |
| `rec_fantasy__category_wins_added`, `…_by_group` | same row counts; measures move; `values_track_rescored_category_wins` returns no row | row counts before and after; the test |
| CI start pool, on #93's fixtures | 4 starts, 3 pitchers, 51 outs (today, after #93: 1, 1, 11) | `int_fantasy__replacement_levels` in `ci.duckdb` |
| CI build | passes with the three warnings it has after #93 | `.agentic/gates` |
| Tenant isolation | 0 differing pairs | gate |
| Value movements | not predicted; recorded by R5.4 | query |
