# Category scales from the league's earlier seasons — requirements

Issue: #57 · Tier: M · Status: proposed 2026-10-08

## Problem

Both value facts divide a category's value over replacement by the category's *margin
scale*: the usual gap between the two sides of a matchup (ADR 0010). The scale is
measured from the matchups of the season being valued, recomputed from our own totals.
ADR 0010 accepted three costs of that and left them to this issue:

- a player's value moves whenever a matchup of his season is restated, even if his own
  production did not;
- the players being valued are in the sides the scale is measured from;
- early in a season the scale rests on few matchups and is noisy.

It also said its evidence, one season of one league, could not show the scale was right.

#85 landed ESPN's reported matchup totals for 2018 to 2025. Measured on them on
2026-10-08, read-only (1,162 decided two-sided matchups, eight seasons, 2020 not played):

- **The 2026 scale is typical.** Per category it is within 10% of the scale pooled over
  all eight seasons, and within 6% for 10 of 17. Season-to-season spread is 5% to 9% for
  most categories, about what sampling alone gives at 143 matchups (6%); stolen bases
  (14%), innings (12%) and ERA (11%) vary more.
- **Margins are close to normal in every season**: 0.206, 0.413 and 0.695 of them lie
  within 0.25, 0.5 and 1 scale units of zero, against 0.197, 0.383 and 0.683 for a normal
  distribution. A player's contribution to one category of one matchup is at most 0.43
  scale units, so the linear form of ADR 0010 holds over the range players occupy.
- **A scale from earlier seasons is as good as a third of the season's own matchups, and
  is there on day one.** Typical error against a season's final scale:

  | Scale measured from | Median error | 90th percentile |
  |---|---|---|
  | The season's first 2 matchup periods (12 matchups) | 19% | 40% |
  | Its first 4 | 11% | 26% |
  | Its first 8 | 7% | 17% |
  | Its first 12 | 5% | 12% |
  | All earlier seasons, pooled | 7% | 16% |

- **A window of recent seasons does no better than all of them** (last 2, 3 or 4 earlier
  seasons against all earlier: mean error 8.0%, 8.3%, 8.7% against 8.1%, 8.3%, 8.6%).
- **A rate's scale and its denominator move together.** ERA's scale is 1.85 over
  earlier seasons, whose sides averaged 159 outs, and 1.64 in 2026, whose sides average
  172: fewer innings, wider gaps in ERA. Taking the scale from one set of matchups and
  the denominator from another moves ERA's values by 12% and WHIP's by 10%; taking both
  from the same matchups moves them by 4% and 2.5%. K/9 goes the other way (5% mixed,
  14% together): its 2026 gaps are wide for the innings pitched.

So the scale is not shown wrong, and the owner chose on 2026-10-08 to change where it is
measured for a different reason: it is noisiest in the first two months of a season,
which is when a valuation is most used.

## Goals

- The margins the platform reported are a model of their own, for every league-season
  loaded, with the number of matchups behind every number.
- A league-season with enough earlier seasons takes its category scales, and the
  denominators that go with them, from those seasons; one without keeps today's method.
  No setting chooses between them.
- A scale says where it came from and how many matchups and seasons are behind it.
- The 2026 values move by what this document says and no more, and the owner's two
  questions from #55 (batter strikeouts; relievers in the top 20) are answered with
  numbers.

## No-gos

- **No fitted model and no win-probability curve.** Value stays linear in the margin
  scale (ADR 0010). The curve was checked and is straight over the range that matters.
- **No choice of method per build or per row.** No `scale_method` key, no variable that
  switches method. The two methods agree too closely (rank correlation 0.999) to pay for
  a second grain.
- **No change to the grain of any model, or to the columns of either value fact.**
- **No new ingestion and no request to ESPN or MLB.**
- **No change to value over replacement, replacement levels or the component rules.**
- **No rosters, complete-games rule or matchup-period mapping for past seasons** (#83).
- **No model of winning the matchup.** How often a matchup turned on one category is not
  measured here.
- **No change to how a scale is measured within a matchup**: home minus away, root mean
  square about zero, every decided matchup counted once whatever its length or playoff
  tier.

## Rabbit holes

- *Weighting recent seasons, or a rolling window* → measured: no better than pooling all.
- *Dropping playoff matchups* → they run 10% to 15% narrower in counting categories, are
  17 of about 143 a season, and move a pooled scale by at most 2.2%. Kept, as today.
- *Adjusting for matchup length* → only 2025 and 2026 carry a per-day breakdown; the
  other seasons' lengths are not known. Every matchup counts once, as ADR 0010 has it.
- *Blending earlier seasons with the current one as it fills in* → a weighting scheme is
  a fitted parameter. Past about a third of a season the two are equally good; the rule
  stays with the one that does not move.
- *A scale for a season with no rosters* → nothing values such a season.
- *Explaining why stolen bases, innings and ERA vary more* → rule changes and how
  managers used pitchers, probably. Recorded, not chased.

## Requirements

### R1. The platform's reported margins

- R1.1 THE SYSTEM SHALL provide `int_fantasy__reported_matchup_margins` with one row per
  (`platform`, `league_id`, `season`, `matchup_id`, `category_key`) for every decided
  two-sided matchup and every category its league-season scores, for every league-season
  loaded, with or without rosters.
- R1.2 THE SYSTEM SHALL give each row the margin the platform reported, home minus away,
  and, for a rate, the two sides' reported denominators.
- R1.3 THE SYSTEM SHALL read which categories are rates, and what their denominators
  are, from `int_fantasy__stat_components`, and SHALL take a denominator from the
  platform's reported stat that is exactly that component. A category with no rule is
  carried as a count.
- R1.4 IF a side has no reported total for a scored category THEN THE SYSTEM SHALL leave
  that matchup's row for the category out.
- R1.5 IF a rate's denominator is not reported for either side of a matchup THEN THE
  SYSTEM SHALL keep the row with null denominators, so that the category's scale and its
  denominator can be measured from the same matchups (R2.3).
- R1.6 THE SYSTEM SHALL NOT include a matchup the platform has not decided, or a bye.

### R2. Reported scales per league-season

- R2.1 THE SYSTEM SHALL provide `int_fantasy__reported_category_scales` with one row per
  (`platform`, `league_id`, `season`, `category_key`) for every scored category of every
  league-season loaded, including a league-season with no decided matchup.
- R2.2 THE SYSTEM SHALL carry `matchups_measured` on every row, zero where there are
  none, with a null scale.
- R2.3 THE SYSTEM SHALL measure a rate's scale and its `side_denominator` from the same
  matchups: those where both sides' denominators are reported. A rate whose denominator
  no matchup reports has `matchups_measured` zero.
- R2.4 THE SYSTEM SHALL compute the scale as the root mean square of the margins, summed
  in a fixed order (spec 0028, R4.13).

### R3. Which scale a league-season's values divide by

- R3.1 WHEN the earlier seasons of the same platform and league hold at least
  `fantasy_scale_min_prior_matchups` measured matchups for a category (default 100) THE
  SYSTEM SHALL give that category, in `int_fantasy__category_scales`, the root mean
  square of all those matchups' reported margins and, for a rate, the mean of their
  sides' reported denominators.
- R3.2 OTHERWISE THE SYSTEM SHALL give the category the scale and denominator it has
  today: from the league-season's own matchups, recomputed from our totals.
- R3.3 THE SYSTEM SHALL pool over matchups, not average the seasons' scales.
- R3.4 THE SYSTEM SHALL NOT use a matchup of the league-season itself, of a later
  season, or of another league or platform in a pooled scale.
- R3.5 THE SYSTEM SHALL take a category's scale and denominator from one source: never a
  pooled scale with the season's own denominator, or the reverse.
- R3.6 THE SYSTEM SHALL add to `int_fantasy__category_scales`: `scale_source`
  (`prior_seasons` or `current_season`) and `seasons_measured`; `matchups_measured`
  SHALL count the matchups behind the scale in use.
- R3.7 THE SYSTEM SHALL keep `int_fantasy__category_scales` at its grain, for
  league-seasons with rosters only (ADR 0026), with exactly the scored categories.
- R3.8 THE SYSTEM SHALL NOT change the SQL of `fct_player_category_value`,
  `fct_player_season_value` or `fct_transaction_impact` beyond their header comments:
  they read the scale they are given.

### R4. Tests

- R4.1 THE SYSTEM SHALL have dbt unit tests for the margins model: a decided matchup
  gives one row per scored category; an undecided matchup and a bye give none; a
  non-scored stat gives none; a rate carries both denominators, and nulls where one is
  unreported; a category with no component rule is a count.
- R4.2 THE SYSTEM SHALL have dbt unit tests for the reported scales: a league-season with
  no decided matchup keeps its categories with zero measured; a rate is measured only
  from matchups with both denominators; the scale is unchanged when home and away are
  swapped.
- R4.3 THE SYSTEM SHALL have dbt unit tests for R3: at the threshold the pooled scale is
  used and one matchup below it is not; pooling is over matchups; the season itself, a
  later season and another league are not pooled; a rate with enough margins but no
  reported denominator falls back whole; the existing unit tests of today's method pass
  with no earlier season given.
- R4.4 THE SYSTEM SHALL have singular tests that: every scored category of every
  league-season has a row in the reported scales; a scale with `scale_source`
  `prior_seasons` rests on at least the threshold; a rate's scale and denominator are
  both null or both present.
- R4.5 THE SYSTEM SHALL keep every existing test of the scales and the value facts, with
  its expectation unchanged where the method in use for its inputs is unchanged.

### R5. The real seasons

- R5.1 THE SYSTEM SHALL build and test clean on the real warehouse, with the warnings it
  has today and no new one.
- R5.2 THE SYSTEM SHALL leave every existing model's rows unchanged except:
  `margin_scale`, `side_denominator`, `matchups_measured` and the two new columns of
  `int_fantasy__category_scales`; and `scaled_value`, `total_value` and the columns
  derived from them in the three value facts.
- R5.3 THE SYSTEM SHALL leave CI's value facts unchanged: no fixture league-season has
  100 earlier matchups.

## Expected values

Measured on 2026-10-08, read-only, on the real warehouse after #87, by the rule of R1 to
R3.

**Matchups measured, per league-season** (`int_fantasy__reported_category_scales`):

| Season | Scored categories | Matchups measured, every category but AVG | AVG |
|---|---|---|---|
| 2018 | 18 | 143 | 0: at-bats not reported |
| 2019 | 18 | 143 | 143 |
| 2020 | 18 | 0: not played | 0 |
| 2021 | 18 | 143 | 143 |
| 2022 | 17 | 143 | 143 |
| 2023 | 17 | 143 | 143 |
| 2024 | 17 | 155 | 155 |
| 2025 | 17 | 149 | 149 |
| 2026 | 17 | 143 | 143 |

**The 2026 scales**, `int_fantasy__category_scales`, all 17 with `scale_source`
`prior_seasons`:

| Category | Today | Reported, 2026 | After | Matchups | Seasons | Denominator today → after | Values multiply by |
|---|---|---|---|---|---|---|---|
| H | 12.7811 | 12.7759 | 12.6466 | 1,019 | 7 | | 1.011 |
| AVG | 0.0450 | 0.0449 | 0.0464 | 876 | 6 | 207.83 → 197.87 | 1.018 |
| HR | 4.1010 | 4.1010 | 4.5333 | 1,019 | 7 | | 0.905 |
| TB | 22.8409 | 22.8365 | 24.5673 | 1,019 | 7 | | 0.930 |
| B_BB | 8.3971 | 8.3971 | 8.0039 | 1,019 | 7 | | 1.049 |
| R | 8.4779 | 8.4779 | 9.2028 | 1,019 | 7 | | 0.921 |
| RBI | 9.9111 | 9.9168 | 10.5143 | 1,019 | 7 | | 0.943 |
| SB | 3.6201 | 3.6201 | 3.4630 | 1,019 | 7 | | 1.045 |
| B_SO | 12.3936 | 12.3936 | 12.7741 | 1,019 | 7 | | 0.970 |
| IP (outs) | 47.1749 | 47.1749 | 50.5701 | 1,019 | 7 | | 0.933 |
| WHIP | 0.2653 | 0.2659 | 0.2948 | 1,019 | 7 | 172.40 → 159.04 | 0.975 |
| ERA | 1.6371 | 1.6553 | 1.8504 | 1,019 | 7 | 172.40 → 159.04 | 0.959 |
| K | 20.3186 | 20.3186 | 19.9243 | 1,019 | 7 | | 1.020 |
| K/9 | 1.9590 | 1.9590 | 1.8597 | 1,019 | 7 | 172.40 → 159.04 | 1.142 |
| W | 2.6391 | 2.6391 | 2.4044 | 1,019 | 7 | | 1.098 |
| L | 2.4947 | 2.4947 | 2.3470 | 1,019 | 7 | | 1.063 |
| SVHD | 3.5988 | 3.6075 | 3.2357 | 590 | 4 | | 1.112 |

"Today" is from our recomputed totals; "Reported, 2026" is the same season from ESPN's,
shown to say the two sources agree (largest difference: ERA, 1.1%).

**The 2026 values**, `fct_player_season_value`, 580 (player, team) pairs:

| Check | Expected | How to verify |
|---|---|---|
| Rank correlation of `total_value`, before against after | 0.9993 | query against a copy kept before the build |
| Top 20, before and after | 19 in common: Wheeler in (21st to 19th), Arozarena out (20th to 22nd) | the same |
| Top 20 by group | 10 SP, 10 hitters, 0 RP → 11 SP, 9 hitters, 0 RP | the same |
| First and second | Crow-Armstrong 36.26, Misiorowski 34.77 → Misiorowski 36.01, Crow-Armstrong 35.24 | the same |
| Largest move in rank among the top 50 / overall | 7 places / 41 places | the same |
| Change in `total_value`: largest / median | 1.29 / 0.087 | the same |
| Median `total_value` by group | hitter 1.32 → 1.29 · SP 1.56 → 1.57 · RP 0.89 → 1.04 | the same |
| Best reliever (the owner's question, #55) | 31st → 26th; none in the top 20 | the same |
| Batter strikeouts (the owner's question, #55) | every B_SO value × 0.970; one player-sd 1.225 → 1.189 scale units | the same |
| Sum of `total_value` | 2,388.89 → 2,405.15 | the same |
| Rows of each value fact | unchanged: 9,860 · 580 · 737 | counts |
| Real build | passes, 1 warning as today | `dbt build` |
| CI | passes; warnings unchanged at 3; value facts identical to before | `.agentic/gates` |
| Tenant isolation | 0 differing pairs over 5 league-seasons | `.agentic/gates` |
