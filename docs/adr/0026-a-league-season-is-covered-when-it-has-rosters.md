# 0026. A league-season is covered when it has rosters, and value models build only for covered ones

- Status: proposed
- Date: 2026-10-08
- Spec: [0085-past-season-matchups](../specs/0085-past-season-matchups/design.md) · Issue: #85

## Context

Every model is keyed by platform, league and season (ADR 0011, spec 0028), but the build
has only ever held league-seasons that are landed whole: settings, matchups, rosters,
transactions and the MLB games to score them. #57 needs the matchup totals of 2018 to
2025 and nothing else of those seasons.

Spikes on 2026-10-08 showed what a league-season with settings and matchups but no
rosters does today. The marts build rows for it, spined on its matchups and categories,
with no values to put in them: four mart tests fail. Two more tests fail for a season
shaped like 2018 to 2021, one because complete games is scored and has no component
rule, one because 2021's matchups carry no per-day breakdown.

## Decision drivers

- A value must never be computed, or reported as missing, for a season whose inputs were
  never landed.
- What is covered should follow from what is loaded, not from a list someone maintains.
- A season that gains rosters later (#83) should need no re-landing and no model change.
- The 2026 season must not move.
- General, not fitted to one league or one season.

## Considered options

1. **Shared staging, and one model that says which league-seasons have rosters**; the
   models that compute values join to it.
2. **A separate endpoint and one narrow model** for past seasons' matchup totals.
3. **A declared list** of covered seasons, in a seed or a variable.
4. **Every model works for every season**, with nulls where inputs are missing.

## Decision

Proposed: **option 1**. The owner chose the shared path on 2026-10-08; the rule and the
model are not yet approved.

`int_fantasy__league_seasons` has one row per league-season with settings loaded, and
`has_rosters`. A model or test that needs rosters applies to league-seasons where it is
true; one that describes what the platform reported applies to all. A league-season with
rosters and no settings or matchups fails the build.

Option 2 files one kind of response under two names and strands a season that later
gains rosters. Option 3 lets the list and the data disagree. Option 4 makes "no rosters"
mean something in every value model, which is a decision about numbers nobody needs.

## Consequences

- Good: a second league, or a past season, can be landed in part without breaking the
  build or producing empty values.
- Good: coverage cannot drift from the data.
- Good: #83 becomes a matter of landing rosters and boxscores.
- Bad / accepted cost: a few intermediate models and tests now depend on one more model.
- Bad / accepted cost: two tests no longer hold for every season. A category of an
  uncovered season may have no component rule, and its scoring periods need not map to
  matchup periods.
- Bad / accepted cost: coverage is a single boolean. A season with rosters and no
  boxscores is "covered" and is caught by the input checks that already exist (#25), not
  by this model.
- Bad / accepted cost: the audit does not know about coverage. It reads the landing
  zone, not dbt, and reports a past season as full of gaps.
