# 0027. A category's scale blends the league's earlier seasons with the season so far

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
- Predicting the scale of the rest of a season, mean error: from the season's first two
  matchup periods 24.5%, from all earlier seasons 8.5%. After sixteen periods the two
  are level at 10.7% and 10.6%.
- Seasons differ for reasons history does not predict. The innings scale went from 42
  outs (2018) to 59 (2023) and back to 44 to 47. Stolen bases rose from about 3.0 to
  about 3.9 with the 2023 rule changes.
- A window of recent seasons predicts no better than all earlier seasons.
- A rate's scale depends on the size of the sides it was measured on: ERA's is 1.85 on
  sides averaging 159 outs and 1.64 on sides averaging 172.

## Decision drivers

- A valuation is used most in the first two months of a season, when the season's own
  scale is at its worst.
- A change in the game (a rule, how pitchers are used, how managers play) should reach
  the scale without anyone having to name it. Raised by the owner on 2026-10-08.
- No fitted or tunable weights (ADR 0010).
- General: a new league, or a category scored for the first time, must still get a
  scale, with no setting to change.
- One answer to what a player is worth.

## Considered options

1. **Measure and report only**: values keep the season's own scale.
2. **Earlier seasons alone**, where they hold enough matchups; the season's own
   otherwise.
3. **Both, selectable** by a key on the facts or a build variable.
4. **Earlier seasons, adjusted for the season's volume** in each counting category.
5. **Earlier seasons counted as a fixed number of matchups, plus the season's own
   decided matchups.**
6. **A declared list of rule changes** that cuts the history for a category.

## Decision

Chosen by the owner on 2026-10-08: **option 5**, with the fixed number equal to the
threshold, 100. The owner first chose option 2, then option 4 when asking how rule
changes would be followed, then option 5 when a test showed option 4 worse than no
adjustment early in a season and unable to follow a change that is not one of volume.

For a category of a league-season, if the earlier seasons of the same platform and
league hold at least 100 decided matchups with a measured margin in that category, the
scale is

    √( (S + 100·p²) / (n + 100) )

where *p* is the root mean square of all those earlier margins and *S* and *n* are the
sum of squares and the count of the league-season's own decided matchups. A rate's side
denominator is the mean over the same matchups' sides with the same weights. With no
matchup decided the scale is *p*. Otherwise both come from the league-season's own
matchups, as ADR 0010 has it. The scale says which (`scale_source`) and what is behind
it.

Agreed by the owner on 2026-10-08, going through the spec's decisions:

- the number 100, counted per category, as the least history used;
- all earlier seasons pooled, with the season's own matchups blended in, in place of a
  window or a volume adjustment;
- the league host's reported totals as the source of everything blended, the season's
  own part included, from decided matchups only. Our recomputed totals remain the
  source only for a league-season with no usable history.

Proposed here and not yet gone through: the rule for a rate's denominator; that a rate
on a zero denominator is not measured.

100 is where a scale's sampling error (about 7%) equals how much seasons differ, so it
is where history and a season's own matchups are equally good evidence. It is used
twice, as threshold and as weight, and is not fitted. History never counts for more
than 100 however much there is: more seasons make *p* more precise, not more relevant.

ADR 0010's unit, its formula and its linear form stand. Its three costs remain for a
league-season with history, in damped form; they apply in full only to one without.

Option 1 keeps the noise where it hurts. Option 2 cannot follow a change: mid-season it
is off by 11.2% on the pitching categories against 8.5% for the blend, and it would have
held 2023's stolen bases 21% low all year. Option 3 pays for a second grain to offer two
numbers that agree to 0.999. Option 4 is worse than option 2 for the first month,
because a season's volume is not known early, and does nothing for a change that is not
one of volume. Option 6 needs a person to keep the list and, in the season of a change,
is option 1.

## Consequences

- Good: a league with history has a scale on the first day of a season.
- Good: a change in the game reaches the scale from the season's own matchups, whatever
  caused it.
- Good: measured, the blend is within 0.3 points of the better of history and the
  season at every stage, and ahead of both from the eighth matchup period.
- Good: a new league or category falls back to the season's own scale by itself.
- Bad / accepted cost: values still move during a season, and a player is still partly
  in the sample that scales him. The weight of the season's own matchups rises to 59%
  by the end of a 143-matchup season.
- Bad / accepted cost: early in the season after a rule change the scale is mostly the
  old one: 19% of the weight is the season's after 24 matchups.
- Bad / accepted cost: 2026's values move. Median change in `total_value` 0.036, largest
  0.51, on a scale where the top value is 36; rank correlation 0.9998.
- Bad / accepted cost: a league-season's values depend on the same league's earlier
  seasons. Loading or correcting an earlier season moves a later one. Leagues remain
  independent of each other ([ADR 0028](0028-a-league-season-may-read-its-leagues-earlier-seasons.md)).
- Bad / accepted cost: 100 is a number in the project, with a stated meaning and not a
  method switch.
- Bad / accepted cost: nothing cuts the history when a league changes size or lineup.
  Not observed in this league.
- Bad / accepted cost: the evidence is one league, eight seasons, 118 category-seasons.
- Follow-ups: #83 (a predictive check with past rosters) remains the only way to show a
  scale predicts winning.
