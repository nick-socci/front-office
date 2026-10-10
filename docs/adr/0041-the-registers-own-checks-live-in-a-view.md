# 0041. The register's own checks live in a view, one row per register row

- Status: accepted
- Date: 2026-10-09
- Spec: [0099-register-keyed-by-league-season](../specs/0099-register-keyed-by-league-season/design.md) · Issue: #99

## Context

Two singular tests judge the register itself. `fct_matchup_scores_match_espn` fails on a
register row that explains no live residual, and `rec_espn__register_matchups_exist`
warns on one whose matchup ESPN does not have. Both join the register by matchup, team
and stat, and both joins change when the register is keyed by league and season
(ADR 0040).

Neither changed join can be seen to be right by a build. On the real season one
league-season has rosters, so a join that forgot the season still finds 31 `registered`
rows. In CI the register names a league that is not loaded, so both queries return the
same thing whatever they join on. dbt can unit-test a model and cannot unit-test a
singular test.

## Decision drivers

- The mistake #99 exists to prevent, a row judged against another league-season, should
  be able to fail a test.
- No change to the grain or statuses of `rec_espn__matchup_stat_differences`.
- A new model, its grain and its columns are the owner's to approve.

## Considered options

1. **A view, `rec_espn__register_rows`**: one row per register row of a loaded
   league-season, with the status of
   the reconciliation row at its full key and a `problem` column; the two tests select
   from it.
2. **Write the full-key join in each test file**, and check it once by hand.
3. **Register-only rows inside `rec_espn__matchup_stat_differences`**, with a new status.

## Decision

Recommended: **option 1**. Grain: one row per (`league_id`, `season`, `matchup_id`,
`team_id`, `stat_id`) of the register whose league-season is loaded. A row about a
league-season that is not loaded is not in the view: the isolation gate (ADR 0013)
treats a row of another league in a single build as a leak, and it would be one. The
warning test reports those rows from the seed. `problem` is `matchup_absent` when ESPN has no such matchup in
that league-season, `explains_nothing` when the reconciliation row at the full key is
missing or is neither `registered` nor `unverified`, and null otherwise. This is the
rule the two tests hold today, with the full key. The pattern is that of
`rec_espn__player_day_residuals` (#81) and `rec_fantasy__category_wins_by_group` (#94).

Option 2 is the smaller diff and leaves the rule untested where it matters. Option 3
changes a table #99 says to leave alone.

## Consequences

- Good: a seven-case unit test holds the rule, including a row whose residual is
  registered in another league-season only.
- Good: the rule is written once; the two tests differ only in which `problem` they
  select.
- Bad / accepted cost: one more relation in the reconciliation schema, 31 rows on the
  real season and none in CI.
- Bad / accepted cost: one piece of the rule, "the league-season is not loaded", stays
  in a test file, checked once by hand.
- Bad / accepted cost: the tests' failing rows change shape, gaining `league_id` and
  `season`.
- Follow-ups: none. Whether `matchup_absent` should be an error for a loaded
  league-season is left as it is.
