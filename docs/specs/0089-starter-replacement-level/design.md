# The replacement level for a start, and a standing check of values against re-scored matchups — design

Issue: #89 · Requirements: [requirements.md](requirements.md)

## Overview

One CTE of `int_fantasy__replacement_levels` changes: which player-days make up the
start pool. Everything downstream reads the level it is given, so the value facts move
without their SQL changing. A new reconciliation model re-scores every decided matchup
with each player swapped for replacement, and a test holds values to what that shows.

```mermaid
flowchart LR
    G[int_mlb__player_game_days] --> L[int_fantasy__replacement_levels]
    R[int_fantasy__roster_days] --> L
    L --> F1[fct_player_category_value]
    L --> F2[fct_transaction_impact]
    F1 --> F3[fct_player_season_value]
    L --> W[rec_fantasy__category_wins_added]
    S[int_fantasy__started_player_days] --> W
    T[int_fantasy__matchup_side_totals] --> W
    F3 -.test: slope by group.-> W
```

## Alternatives considered

Each was built on 2026 and its effect computed (requirements.md has the levels).

| | A. Today: top N by free-agent starts over the season | **B. Every free-agent start by a pitcher who was a starter at the time** | C. Best free agents each day, ranked on their season to date | D. Most-used free agents each matchup period | E. Players the league added and dropped | F. The tier beyond the league's demand |
|---|---|---|---|---|---|---|
| Start ERA / outs | 5.41 / 15.0 | 4.90 / 14.9 | 4.84 / 13.4 | 5.17 / 15.2 | 4.39 / 15.5 | 4.19–4.45 / 15.4–15.9 |
| Stable when its parameter moves | 5.40 / 5.41 / 5.06 at N = 6 / 12 / 24 | no parameter; 4.87–4.93 across four cuts | 4.66 / 4.84 / 4.84 | 5.88 / 5.17 / 4.97 | 4.16–4.39 across three wordings | 4.19 / 4.45 / 4.48 |
| Hindsight | whole season | none | none | none | whole season | whole season |
| Rests on managers' moves | no | no | no | no | yes | no |
| Length of a relief outing, if applied to relief | 2.80 | not applied | 3.67 | 2.77 | 3.60 | 2.94 |
| Top 20, SP / hitters | 11 / 9 | 9 / 11 | 11 / 9 | not computed | 7 / 13 | 11 / 9 |

- **A** is half a run too lenient on ERA: its pool is the pitchers nobody wanted.
- **C** was the owner's first choice. For starters its ranking selects nobody (about 11
  free-agent starters a day), so it is B plus openers; for relievers it brings back long
  outings.
- **D** is today's principle made point-in-time, and shows why usage cannot rank
  starters: the most-used free-agent starters are the worst.
- **E** was rejected by the owner, and removing the 14 days before a pickup moves a
  similar pool from 4.20 to 4.79.
- **F** is the textbook definition; its tier is lifted by stars with half a season.

B is applied to starts only. For relievers an unranked pool is ADR 0009's rejected
option 4 (3.58 outs an appearance, call-ups and position players); for hitters it is
bench players with one at-bat (1.14 total bases a game). Those kinds need a ranking to
find the players doing the job, and for them usage is not adversely selected.

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0029](../../adr/0029-the-start-pool-is-every-free-agent-start-by-a-starter.md) | The start pool is every free-agent start by a pitcher who was a starter at the time, unranked; amends ADRs 0001 and 0009 for the start kind | proposed |

## Detailed design

### `int_fantasy__replacement_levels`

Grain and columns unchanged. `pitching_pool` today ranks both kinds by appearances and
keeps the top N. It is split:

- **relief**: as today.
- **start**: no player-level pool. `start_pool_days` is the free-agent days whose
  `fo_pitching_day_kind` is `start` and whose pitcher's role to date is `SP`.

Role to date: `fo_replacement_group` applied to the sums of the pitcher's
`plate_appearances`, `batters_faced`, `outs_recorded`, `games_pitched` and
`games_started` over `int_mlb__player_game_days` of the same season with `game_date`
before the day, by a window over the player's days. The macro is the one
`dim_players` and the batting pool already use, so "a starter" has one meaning. A
pitcher's first appearance of a season has no totals and is not `SP`; 120 such starts
are left out in 2026, with 465 by pitchers who were relievers up to then (openers, 9.4
outs).

`pool_played_days` for the start kind then counts `start_pool_days`, and
`pool_players` its distinct pitchers. The header's DEFINITION, BIAS and SENSITIVITY
sections are rewritten for the start kind, with the table of requirements.md.

The roles are decided from all MLB days, not only free-agent ones: what a pitcher has
been doing is the same whoever rosters him.

### The value facts

No SQL change. `fct_transaction_impact` moves with the others; it reads the same level.

### `rec_fantasy__category_wins_added`

The owner agreed its grain and columns on 2026-10-09, and that it stays a
reconciliation model, not a mart.

In `models/reconciliation/fantasy/`, a table. Grain: (`platform`, `league_id`, `season`,
`platform_player_id`, `fantasy_team_id`). League-seasons with rosters only.

| Column | Meaning |
|---|---|
| `matchups_rescored` | re-scorable matchups in which the pair had a started day: `fct_matchup_results` gives a winner and `has_unverified_inputs` is false |
| `category_wins_added` | actual category points minus points with replacement in his place, summed over those matchups and scored categories; a win is 1, a tie one half; averaged over the draws |
| `matchup_wins_added` | the same for the matchup, decided by most categories |

Steps, all in components (AGENTS.md rule 4):

1. The pair's components and played days by kind in each matchup, from
   `int_fantasy__started_player_days`, the dates of `int_fantasy__matchup_periods` and
   the sides of `int_fantasy__matchup_sides`.
2. Replacement's expected components: played days of each kind times that kind's level.
3. Twenty draws. A draw's amount is the floor of the expectation plus 1 when a uniform
   number is below its fraction. The uniform number is the first 32 bits of the MD5 of
   the pair, matchup, component and draw number, over 2³²: the same on every build and
   every DuckDB version, which `hash()` does not promise.
4. The side's totals from `int_fantasy__matchup_side_totals`, minus the pair's, plus the
   draw's.
5. Every scored category's value for that side by the rules, and its result against the
   opponent's actual value, rounded to 9 places as `fct_matchup_category_scores` does. A
   category undefined on either side in a draw is left out of that draw.
6. Sum and average.

The matchups are all re-scorable ones, playoffs included: the values being checked count
every started day. All 143 matchups of 2026 are re-scorable (none has unverified
inputs); the fixture's are not, so in CI the model is empty.

If a kind of day the pair played in such a matchup has a null level, both measures are
null for the pair, by the rule the value facts follow for an empty pool, and the row
stays.

### The test

If margins are normal with the scale as their root mean square, a small contribution of
*x* scale units changes the expected result by *x*/√(2π) = 0.399*x*. So the slope
through the origin of `category_wins_added` on `total_value`, Σ(wins × value) / Σ(value²),
should be about 0.40 for every group of players, and equal between groups if the model
is even-handed. Measured after the change: 0.43 for starters, 0.40 for hitters, 0.33
for relievers.

`values_track_rescored_category_wins` fails for a judged group whose slope is outside
0.34 to 0.47, about 15% either side of 0.40. Scaling a group's values by a factor *f*
divides its slope by *f*, so it fails when starters' values are inflated by about a
quarter (0.43 / 0.34) or hitters' by 18%, and when either is deflated by 9% to 15%.

A group is judged when it has at least 100 pairs and its two measures correlate at 0.75
or more. Starters (0.85) and hitters (0.81) are; relievers (0.69) are not. The owner
chose this on 2026-10-09 over one band of 0.30 to 0.50 for every group, which had to be
loose enough for the relievers and so guarded nothing well. The question the issue asked
is whether starters are overvalued against hitters, and this is the test of it. The
exclusion is by a measure and not by name: relief values are the model's known weak
spot (ADR 0009), and a relief group whose values came to track real wins would be
judged without the test changing.

`rec_fantasy__category_wins_by_group`, a view over the model and
`fct_player_season_value`, holds each league-season and group's pairs, slope,
correlation and whether it is judged. The test reads it, and so does the run evidence,
so the relievers' figure is on record every time (R3.9).

A group of 100 or more pairs with a pair whose value or wins added is null fails as not
checkable, judged or not, so a slope is never computed from part of a group.

