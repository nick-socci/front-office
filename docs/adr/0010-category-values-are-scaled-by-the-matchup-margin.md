# 0010. Category values are scaled by the matchup margin

- Status: proposed
- Date: 2026-10-03
- Spec: [0055-matchup-margin-scale](../specs/0055-matchup-margin-scale/design.md) · Issue: #55

## Context

[ADR 0003](0003-total-value-is-a-sum-of-standardised-category-values.md) divides each
category's value over replacement by its standard deviation across (player, team) pairs
and sums the results with equal weight. It named its own weakness, that all categories
are treated as equally valuable, and named win-probability weighting as the better answer
in principle.

After #52 measured pitchers like for like, the pitching spreads shrank (innings 115.6 to
25.4 outs) and starters took 15 of the top 20 values. The owner did not accept that as
settled.

Measured on the 143 matchups of 2026, one player-standard deviation is worth, in units of
how far apart two teams finish in that category: IP 0.54, W 0.81, L 0.80, AVG 0.97, K
1.02, RBI 1.09, H 1.11, TB 1.26, SV+HD 1.26, K/9 1.31, ERA 1.34, R 1.40, WHIP 1.43, HR
1.47, B_BB 1.60, B_SO 1.81, SB 2.01. Equal weights on player spread therefore pay nearly
four times as much for a matchup margin of innings as for one of stolen bases.

What the summary number means is the owner's decision.

## Decision drivers

- The unit should be the one the league is decided in: a category is won by finishing
  ahead in it, so what matters is production relative to the gap between teams.
- No fitted or tunable weights.
- Computable from data already modelled, and explainable in a model header.
- One scalar for #11's facts and for #12.

## Considered options

1. **Keep ADR 0003** — divide by the spread across players.
2. **Scale by the matchup margin** — divide by the root mean square difference between
   the two sides of a matchup in that category; convert a rate's value to rate units with
   the typical side denominator first.
3. **No scalar across sides** — report a batting total and a pitching total, and never
   compare a hitter with a pitcher.
4. **Fitted win probability** — model each category's margin distribution and convert
   value to expected category wins.

## Decision

Chosen: **scale by the matchup margin**. `standardised_value` is renamed `scaled_value`
and becomes value over
replacement, in the category's own units, divided by the category's margin scale;
`total_value` remains the plain sum over scored categories. It reads as "matchup margins
added over a free agent, summed across categories".

Option 1 answers how unusual a player is, which is not what a manager is paid in. Option
3 is honest but leaves transaction impact unable to say whether dropping a hitter for a
pitcher helped, and gives up the comparison the facts exist to make. Option 4 is the
right end point, but the linear version of it is visibly rough on one season: across
teams, a margin of value buys 0.26 net category wins in RBI and 1.60 in SV+HD. A fitted
model needs more than 143 matchups and its own validation.

Under the chosen scale the top 20 is 10 starters and 10 hitters, and the medians are
hitter +1.32, SP +1.56, RP +0.89.

## Consequences

- Good: no parameters; the weights between categories come from the league's own
  matchups; hitters' walks, steals and strikeouts are no longer discounted.
- Bad / accepted cost: the evidence cannot show this scale is *better*. Per category it
  is the same value times a constant, so only the cross-category weighting differs, and
  the one test of that, team totals against net category wins, is 12 teams: correlation
  0.85 against 0.81 for ADR 0003. The case is that it is the right unit.
- Bad / accepted cost: a rate's conversion assumes a typical team's denominator (172.4
  outs, 207.8 at-bats a matchup); a pitcher's effect on a team with fewer innings is
  larger than stated.
- Bad / accepted cost: the scale comes from one season of one league, and includes two
  long matchup periods (12 and 14 days). Without them the scales move by up to 7% (IP).
- Bad / accepted cost: the league's scoring type is `H2H_MOST_CATEGORIES`: a matchup is
  won by taking the most categories. This scale treats a margin alike in every category
  and every week, whether or not that category was the one that decided the matchup. A
  model of winning the matchup would not.
- Bad / accepted cost: player value now depends on matchup results, so the value facts
  rebuild whenever a matchup is restated.
- Supersedes the denominator of ADR 0003. Its plain sum and "no mean subtracted" stand:
  one matchup margin counts the same in every category. A unit of `total_value` is a
  margin, not a category win; the two are not proportional (see option 4). #12 uses this
  scalar.
- Follow-ups: #57 lands earlier seasons' matchup scores (the league has 2009 to 2025) and
  backtests a fitted win-probability scale; blocked by #28.
