# Category scales from the league's earlier seasons and the season so far — requirements

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
- **Earlier seasons are a better guide early, the season itself a better guide late, and
  a blend of the two is as good as the better one throughout.** Predicting the scale of
  the *rest* of a season from what is known after *k* matchup periods, mean error over
  118 category-seasons:

  | Known so far | Earlier seasons only | The season so far only | Blend |
  |---|---|---|---|
  | 2 periods (12 matchups) | 8.5% | 24.5% | 8.8% |
  | 4 periods (24) | 8.7% | 15.7% | 8.8% |
  | 8 periods (48) | 8.9% | 11.6% | 8.4% |
  | 12 periods (72) | 9.7% | 10.7% | 9.2% |
  | 16 periods (96) | 10.6% | 10.7% | 9.6% |

  The blend counts the earlier seasons as 100 matchups and adds the season's decided
  matchups to them. The floor is about 7%: the rest of a season is itself a sample.
- **What changes between seasons is not a trend that history predicts.** The innings
  scale rose from 42 to 59 outs between 2018 and 2023 and fell back to 44 to 47. For
  innings, strikeouts, ERA and WHIP, 12 periods in, earlier seasons alone are off by
  11.2% and the blend by 8.5%. The stolen-base scale rose from about 3.0 to about 3.9
  with the 2023 rule changes.
- **Adjusting a pooled scale for the season's volume was tried and dropped.** A count's
  scale does follow the square root of its volume (stolen bases: 14% spread between
  seasons, 5% once divided by it), but the season's average is not known early: the
  opening matchup period is long, the average after two periods is off by 19%, and the
  adjusted scale is worse than the unadjusted one for the first month (11.9% against
  8.5%).
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
which is when a valuation is most used. The owner first chose a scale pooled from
earlier seasons alone, then, asking how rule changes and changes in pitcher usage would
be followed, chose the blend.

## Goals

- The margins the platform reported are a model of their own, for every league-season
  loaded, with the number of matchups behind every number.
- A league-season with enough earlier seasons takes its category scales, and the
  denominators that go with them, from those seasons and its own decided matchups
  together, the earlier seasons counting as a fixed number of matchups; one without
  keeps today's method. No setting chooses between them.
- A change in the game, whatever its cause, reaches the scale as the season's matchups
  are decided, without anyone naming it.
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
- **No new fixture data.** The isolation check exercises the blended scale by lowering
  the variable for its own builds, on the fixtures that exist.
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
- *Adjusting for a category's volume, or a list of rule changes* → the first is worse
  early (see *Problem*); the second needs someone to keep it and does worst in the season
  a rule changes. The blend follows a change from the season's own matchups.
- *Fitting the weight of the earlier seasons* → it is the threshold, 100: where a scale
  from that many matchups is as uncertain as seasons differ. Not tuned.
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
- R1.7 THE SYSTEM SHALL carry `is_measured` on every row: true for a count; for a rate,
  true only when both sides' denominators are reported and greater than zero. A rate on
  a zero denominator is undefined, as it is in `int_fantasy__matchup_stat_values`, even
  where the platform reports it as zero.
- R1.6 THE SYSTEM SHALL NOT include a matchup the platform has not decided, or a bye.

### R2. Reported scales per league-season

- R2.1 THE SYSTEM SHALL provide `int_fantasy__reported_category_scales` with one row per
  (`platform`, `league_id`, `season`, `category_key`) for every scored category of every
  league-season loaded, including a league-season with no decided matchup.
- R2.2 THE SYSTEM SHALL carry `matchups_measured` on every row, zero where there are
  none, with a null scale.
- R2.3 THE SYSTEM SHALL measure a scale, and a rate's `side_denominator`, from the rows
  with `is_measured` and no others, so that a rate's scale and denominator come from the
  same matchups. A rate whose denominator no matchup reports has `matchups_measured`
  zero.
- R2.4 THE SYSTEM SHALL compute every scale as the root mean square of the margins,
  summed in the order (`season`, `matchup_id`), which is unique within a league: ESPN
  reuses matchup ids across seasons (158 distinct ids over 1,162 matchups), and the last
  digit of a floating-point sum depends on the order of its terms (spec 0028, R4.13).
  This holds for the sums of R3.1 as well.

### R3. Which scale a league-season's values divide by

`fantasy_scale_prior_matchups` is one dbt variable, default 100. It is both the least
history that is used and what that history counts as.

- R3.1 WHEN the earlier seasons of the same platform and league hold at least
  `fantasy_scale_prior_matchups` measured matchups for a category THE SYSTEM SHALL give
  that category, in `int_fantasy__category_scales`, the blended scale
  √((*S* + *w*·*p*²) / (*n* + *w*)), where *p* is the root mean square of all those
  earlier margins, *w* is the variable, and *S* and *n* are the sum of squares and the
  count of the league-season's own measured margins.
- R3.2 WHEN R3.1 applies to a rate THE SYSTEM SHALL give it the side denominator
  (*D* + 2*w*·*q*) / (2*n* + 2*w*), where *q* is the mean reported denominator of the
  earlier matchups' sides and *D* is the sum of the league-season's own measured sides'
  denominators: the same matchups, with the same weights, as the scale.
- R3.3 WHEN a league-season has no decided matchup and R3.1 applies THE SYSTEM SHALL give
  the category exactly *p* and *q*.
- R3.4 OTHERWISE THE SYSTEM SHALL give the category the scale and denominator it has
  today: from the league-season's own matchups, recomputed from our totals.
- R3.5 THE SYSTEM SHALL pool the earlier seasons over matchups, not average the seasons'
  scales, and SHALL take every margin of R3.1 to R3.3, the league-season's own included,
  from `int_fantasy__reported_matchup_margins` rows with `is_measured`.
- R3.6 THE SYSTEM SHALL NOT use a matchup of a later season, or of another league or
  platform.
- R3.7 THE SYSTEM SHALL add to `int_fantasy__category_scales`: `scale_source`
  (`prior_and_current_seasons` or `current_season`), `prior_matchups_measured`,
  `prior_seasons_measured` and `prior_margin_scale` (*p*; null under `current_season`).
  `matchups_measured` SHALL count the league-season's own matchups behind the scale,
  as it does today.
- R3.8 THE SYSTEM SHALL keep `int_fantasy__category_scales` at its grain, for
  league-seasons with rosters only (ADR 0026), with exactly the scored categories.
- R3.9 THE SYSTEM SHALL NOT change the SQL of `fct_player_category_value`,
  `fct_player_season_value` or `fct_transaction_impact` beyond their header comments:
  they read the scale they are given.

### R4. Tests

- R4.1 THE SYSTEM SHALL have dbt unit tests for the margins model: a decided matchup
  gives one row per scored category; an undecided matchup and a bye give none; a
  non-scored stat gives none; a rate carries both denominators, and nulls where one is
  unreported; a decided matchup with a side on a zero denominator is a row that is not
  measured; a category with no component rule is a count.
- R4.2 THE SYSTEM SHALL have dbt unit tests for the reported scales: a league-season with
  no decided matchup keeps its categories with zero measured; a rate is measured only
  from matchups with both denominators; the scale is unchanged when home and away are
  swapped.
- R4.3 THE SYSTEM SHALL have dbt unit tests for R3: at the threshold the blend is used
  and one matchup below it is not; the blend's value for hand-computed inputs, for a
  count and for a rate with its denominator; a season with no decided matchup takes the
  earlier seasons' scale exactly; pooling is over matchups; a later season and another
  league are not used; an undecided matchup of the season is not used; a rate with
  enough margins but no reported denominator falls back whole; the existing unit tests
  of today's method pass with no earlier season given.
- R4.4 THE SYSTEM SHALL have singular tests that: every scored category of every
  league-season has a row in the reported scales; a scale with `scale_source`
  `prior_and_current_seasons` rests on at least the threshold of earlier matchups, has a
  scale, and for a rate a denominator. A `current_season` row is not held to that: today's method can give a
  rate a denominator and no scale (one side defined, the other on a zero denominator),
  and R3.4 keeps it as it is.
- R4.5 THE SYSTEM SHALL keep every existing test of the scales and the value facts, with
  its expectation unchanged where the method in use for its inputs is unchanged.

### R5. Isolation between leagues

A league-season's scales now read the same league's earlier seasons by design, which the
isolation check of ADR 0013 forbids as written: it builds each league-season alone.

- R5.1 THE SYSTEM SHALL have `scripts/check_tenant_isolation.py` build, for each
  league-season, that league's captures of that season and of every earlier season, with
  the MLB data of those seasons, and compare the rows of that league-season with the
  combined build's, relation by relation, as it does today.
- R5.2 THE SYSTEM SHALL run every build of that check, combined and single, with
  `fantasy_scale_prior_matchups` set to 2, so that the blended scale is in use for
  the fixture league-seasons that have an earlier season, and a league-season with none
  falls back in the same run.
- R5.3 THE SYSTEM SHALL fail the check if another league's captures, or a later
  season's, change a league-season's rows.
- R5.4 THE SYSTEM SHALL leave the main CI build at the default threshold, so that its
  value facts do not move (R6.3).

### R6. The real seasons

- R6.1 THE SYSTEM SHALL build and test clean on the real warehouse, with the warnings it
  has today and no new one.
- R6.2 THE SYSTEM SHALL leave every existing model's rows unchanged except:
  `margin_scale`, `side_denominator` and the four new columns of
  `int_fantasy__category_scales`; and `scaled_value`, `total_value` and the columns
  derived from them in the three value facts.
- R6.3 THE SYSTEM SHALL leave CI's value facts unchanged: no fixture league-season has
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
`prior_and_current_seasons` and `matchups_measured` 143:

| Category | Today | Earlier seasons (*p*) | After (blended) | Earlier matchups | Seasons | Denominator today → earlier → after | Values multiply by |
|---|---|---|---|---|---|---|---|
| H | 12.7811 | 12.6466 | 12.7228 | 1,019 | 7 | | 1.005 |
| AVG | 0.0450 | 0.0464 | 0.0455 | 876 | 6 | 207.83 → 197.87 → 203.73 | 1.007 |
| HR | 4.1010 | 4.5333 | 4.2842 | 1,019 | 7 | | 0.957 |
| TB | 22.8409 | 24.5673 | 23.5641 | 1,019 | 7 | | 0.969 |
| B_BB | 8.3971 | 8.0039 | 8.2375 | 1,019 | 7 | | 1.019 |
| R | 8.4779 | 9.2028 | 8.7834 | 1,019 | 7 | | 0.965 |
| RBI | 9.9111 | 10.5143 | 10.1669 | 1,019 | 7 | | 0.975 |
| SB | 3.6201 | 3.4630 | 3.5563 | 1,019 | 7 | | 1.018 |
| B_SO | 12.3936 | 12.7741 | 12.5516 | 1,019 | 7 | | 0.987 |
| IP (outs) | 47.1749 | 50.5701 | 48.6009 | 1,019 | 7 | | 0.971 |
| WHIP | 0.2653 | 0.2948 | 0.2782 | 1,019 | 7 | 172.40 → 159.04 → 166.90 | 0.985 |
| ERA | 1.6371 | 1.8504 | 1.7382 | 1,019 | 7 | 172.40 → 159.04 → 166.90 | 0.973 |
| K | 20.3186 | 19.9243 | 20.1573 | 1,019 | 7 | | 1.008 |
| K/9 | 1.9590 | 1.8597 | 1.9187 | 1,019 | 7 | 172.40 → 159.04 → 166.90 | 1.055 |
| W | 2.6391 | 2.4044 | 2.5452 | 1,019 | 7 | | 1.037 |
| L | 2.4947 | 2.3470 | 2.4350 | 1,019 | 7 | | 1.025 |
| SVHD | 3.5988 | 3.2357 | 3.4593 | 590 | 4 | | 1.040 |

"Today" is from our recomputed totals. The blend's own-season part is from ESPN's
reported totals, which differ from ours by at most 1.1% in a 2026 scale (ERA). With 143
of its own matchups against 100 for the earlier seasons, 2026 carries 59% of the weight.

**The 2026 values**, `fct_player_season_value`, 580 (player, team) pairs:

| Check | Expected | How to verify |
|---|---|---|
| Rank correlation of `total_value`, before against after | 0.9998 | query against a copy kept before the build |
| Top 20, before and after | 19 in common: Wheeler in (21st to 20th), Arozarena out (20th to 21st) | the same |
| Top 20 by group | 10 SP, 10 hitters, 0 RP → 11 SP, 9 hitters, 0 RP | the same |
| First three | Crow-Armstrong 36.26, Misiorowski 34.77, Ohtani 33.57 → 35.78, 35.13, 33.35, in the same order | the same |
| Largest move in rank among the top 50 / overall | 4 places / 22 places | the same |
| Change in `total_value`: largest / median | 0.51 / 0.036 | the same |
| Median `total_value` by group | hitter 1.32 → 1.31 · SP 1.56 → 1.56 · RP 0.89 → 0.92 | the same |
| Best reliever (the owner's question, #55) | 31st → 29th; none in the top 20 | the same |
| Batter strikeouts (the owner's question, #55) | every B_SO value × 0.987; one player-sd 1.225 → 1.210 scale units | the same |
| Sum of `total_value` | 2,388.89 → 2,388.24 | the same |
| Rows of each value fact | unchanged: 9,860 · 580 · 737 | counts |
| Real build | passes, 1 warning as today | `dbt build` |
| CI | passes; warnings unchanged at 3; value facts identical to before | `.agentic/gates` |
| Tenant isolation, each league-season built with its league's earlier seasons, variable set to 2 | 0 differing pairs over 5 league-seasons; `scale_source` is `prior_and_current_seasons` for (111111, 2026), (111111, 2027) and (222222, 2027), and `current_season` for (222222, 2026) | `.agentic/gates`, and a query on the kept combined warehouse |
