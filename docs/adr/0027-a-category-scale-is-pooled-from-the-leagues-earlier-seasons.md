# 0027. A category's scale is pooled from the league's earlier seasons where it has them

- Status: proposed
- Date: 2026-10-08
- Spec: [0057-category-scales-from-history](../specs/0057-category-scales-from-history/design.md) · Issue: #57
- Amends: [0010](0010-category-values-are-scaled-by-the-matchup-margin.md)

## Context

ADR 0010 scales a category's value by its matchup margin: the root mean square gap
between the two sides of a matchup. It measures that from the matchups of the season
being valued and accepted three costs: values move when a matchup is restated, the
players valued are inside the sample, and the scale is noisy early in a season. It also
said one season of one league could not show the scale was right.

ESPN's reported totals for 2018 to 2025 are now loaded (#85): 1,019 decided matchups
before 2026. Measured on 2026-10-08:

- 2026's scale is within 10% of the eight-season pooled scale in every category. Margins
  are near normal in every season. Nothing shows the scale or its linear form wrong.
- Against a season's final scale, a scale from its first two matchup periods is off by
  19% (median), from its first eight by 7%, and from all earlier seasons by 7%.
- A window of recent seasons predicts no better than all earlier seasons.
- A rate's scale depends on the size of the sides it was measured on: ERA's is 1.85 on
  sides averaging 159 outs and 1.64 on sides averaging 172.
- With the scale and denominator both taken from earlier seasons, 2026's player ranking
  correlates 0.9993 with today's; 19 of the top 20 are the same.

## Decision drivers

- A valuation is used most in the first two months of a season, when the season's own
  scale is at its worst.
- No fitted or tunable weights (ADR 0010).
- General: a new league, or a category scored for the first time, must still get a
  scale, with no setting to change.
- One answer to what a player is worth.

## Considered options

1. **Measure and report only**: values keep the season's own scale.
2. **Earlier seasons where they hold enough matchups, the season's own otherwise.**
3. **Both, selectable** by a key on the facts or a build variable.
4. **A blend** of earlier seasons and the season so far, weighted by how much is played.

## Decision

Proposed: **option 2**. The owner chose it over options 1 and 3 on 2026-10-08; the
threshold, the seasons pooled, the source of the totals and the rule for a rate's
denominator are proposed here.

For a category of a league-season, if the earlier seasons of the same platform and
league hold at least 100 decided matchups with a reported margin in that category, the
scale is the root mean square of all those margins, and a rate's side denominator is
the mean reported denominator of those same matchups' sides. Otherwise both come from
the league-season's own matchups, as ADR 0010 has it. The scale says which
(`scale_source`) and how many matchups and seasons are behind it.

All earlier seasons are pooled, over matchups. The platform's reported totals are used
for every earlier season, whether or not it has rosters. A rate's scale and denominator
always come from the same matchups; a rate whose denominator earlier seasons do not
report keeps the season's own for both.

ADR 0010's unit, its formula and its linear form stand. What it says about where the
scale is measured, and the three costs that followed from it, now apply only to a
league-season with no usable history.

Option 1 keeps the noise where it hurts. Option 3 pays for a second grain to offer two
numbers that agree to 0.999. Option 4 needs a weighting curve, which is a fitted
parameter.

## Consequences

- Good: a league with history has a scale on the first day of a season, and it does not
  move during the season.
- Good: with history, a player's value no longer depends on other players' matchups of
  the same season being restated, and he is not in the sample that scales him.
- Good: a new league or category falls back to the season's own scale by itself.
- Bad / accepted cost: 2026's values move. Median change in `total_value` 0.087, largest
  1.29, on a scale where the top value is 36; the first two players swap; K/9 values
  rise 14%, wins 10% and SVHD 11%; HR values fall 9.5%.
- Bad / accepted cost: a season that is unusual (a rule change, as with stolen bases
  from 2023) is valued on a scale from seasons that were not. Stolen bases, innings and
  ERA vary 11% to 14% between seasons.
- Bad / accepted cost: a league-season's values now depend on the same league's earlier
  seasons. Loading or correcting an earlier season moves a later one. Leagues remain
  independent of each other.
- Bad / accepted cost: one threshold, 100 matchups, is a number in the project. It marks
  where a pooled scale stops being better than noise (a standard error of about 7%),
  and is not a method switch.
- Bad / accepted cost: nothing cuts the history when a league changes size or lineup.
  Not observed in this league.
- Follow-ups: #83 (a predictive check with past rosters) remains the only way to show a
  scale predicts winning.
