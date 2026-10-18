# 0081. The higher seed is found as the home side, and a test holds home to the better seed

- Status: proposed
- Date: 2026-10-18
- Spec: [0159-playoff-tiebreak](../specs/0159-playoff-tiebreak/design.md) · Issue: #159

## Context

ADR 0080 gives a level playoff matchup to the higher seed. Seeds are staged only in
`stg_espn__teams` (`playoff_seed`), from the teams endpoint. That endpoint holds member
data, and how such endpoints reach BigQuery is undecided (#136). `fct_matchup_results` is
in the BigQuery slice (ADR 0051). ESPN seats the better seed at home in all 136 playoff
matchups of eight seasons, across the winners' bracket and both consolation ladders
(spec 0159, C2). The slice selects a test only when every parent of the test is in the
slice (C9).

## Decision drivers

- `fct_matchup_results` stays in the BigQuery slice, so #136 isn't forced early.
- The rule is checked against ESPN's own seeds, not assumed.

## Considered options

1. **The home side, held by a test.** The model gives a level playoff matchup to `HOME`. A
   singular test reads both sides' `playoff_seed` and fails when the home seed is not the
   better one.
2. **Read the seeds in the model.** Join `stg_espn__teams` and give the matchup to the
   better seed.

## Decision

Chosen by the owner on 2026-10-18: **option 1**. The model reads nothing new and stays in
the slice. The test checks, on every DuckDB build, that home is where the higher seed sits,
and it stays out of the slice because one of its parents is not in it.

## Consequences

- Good: no dependency on #136. The 136 matchups pass, and a change in how ESPN seats teams
  fails the build by name.
- Bad / accepted cost: the model states the rule through ESPN's placement, not through the
  seed itself. On BigQuery the guard does not run until #136 brings the teams endpoint
  there.
- Follow-ups: if the test ever fails, or once #136 lands, reading the seeds (option 2) is a
  small change to the model.
