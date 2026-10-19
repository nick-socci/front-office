# 0086. History in a category's scale counts for the season's matchups not yet played

- Status: proposed
- Date: 2026-10-18
- Spec: [0161-scale-follows-the-season](../specs/0161-scale-follows-the-season/design.md) · Issue: #161
- Amends: [0027](0027-a-category-scale-blends-the-leagues-earlier-seasons-with-the-season-so-far.md)

## Context

ADR 0027 blends a category's scale, √((S + w·p²) / (n + w)), with the earlier seasons
counted as a fixed w = 100 matchups. In a finished season of 126 matchups, history still
carries 44% of the weight (spec 0161, C4).

2023 was MLB's first season under the pitch clock. In six of its seven pitching
categories the blended scales undershot the season's own margins, by 3% to 9% (C3).
Starters' values were inflated, and their slope fell to 0.3333, below the floor of
`values_track_rescored_category_wins` (C1). Scored on the season's own scale, the slope is
0.3474 (C6).

ADR 0027 measured that history predicts a season better early on, and the season itself
better after sixteen periods (C13). The owner framed #161 as a tilt to fix, not a band to
widen (2026-10-18).

## Decision drivers

- The scale estimates the margin of the season being valued (ADR 0010).
- A valuation is used most early in a season, when history is the better guide (ADR 0027).
- A change in the game reaches the scale without anyone naming it (ADR 0027).
- No fitted or tunable weight (ADR 0027).
- General: no league, season or rule is named.

## Considered options

1. **History counts for the matchups not yet played**, w = max(0, M − n), with M the
   league-season's scheduled regular-season matchups.
2. **The same, capped at 100**: min(100, M − n).
3. **A linear fade**: 100 × (1 − n / M).
4. **A lower fixed weight** (25).
5. **Keep ADR 0027 and move the band.**

M from the settings (matchup period count × floor(team count / 2)), or from the
scheduled matchups of the matchups endpoint.

## Decision

Chosen by the owner on 2026-10-18: **option 1, with M from the settings**. The scale then
estimates the whole season's margin: n matchups are measured, and M − n are predicted by
history. It is p
before the first matchup, within a point of ADR 0027 after two periods (w = 114 against
100), and the season's own once every matchup is played. No number in it is tuned.
Backtested on seven seasons' margins (C17), it is never worse than the fixed 100. The two
are equal through six periods, and it is better from eight on: 3.3% against 4.5% mean
error against the season's margin after sixteen periods.

Option 2 equals it once 100 or fewer matchups remain, but keeps a tuned cap. Option 3's
middle is a schedule, not an estimate. Option 4 is a tuned weight and leaves a finished
season leaning on history. Option 5 is against the owner's framing.

Every landed settings capture holds M (C9), though all are from late in their seasons,
so whether it is set before a season starts is not shown (spec 0161, *Open questions*).
Whether the matchups endpoint lists future matchups in-season is unproven too.

`fantasy_scale_prior_matchups` stays as the threshold for using history at all (100
earlier matchups); it is no longer the weight, except as a fallback. A league-season whose
settings give no positive M is scaled as ADR 0027 has it, with a warning that names it
(owner, 2026-10-18).

## Consequences

- Good: a finished season's values rest on that season alone, and 2023's starters pass
  the check with the band unchanged. A changed game reaches the scale fully by the end of
  its first season.
- Bad / accepted cost: every value from 2019 on moves, and with it the optimal lineups,
  lineup decisions and transaction impact (C10). The in-season behaviour is reasoned from
  ADR 0027's measurements and a retrospective backtest (C17). It is not measured on
  in-season captures, which are not landed.
- Follow-ups: starters and hitters both sit a little below 0.40 across seasons (spec 0161,
  *Open questions*). Revisit if a league's schedule changes mid-season often enough to
  make M stale.
