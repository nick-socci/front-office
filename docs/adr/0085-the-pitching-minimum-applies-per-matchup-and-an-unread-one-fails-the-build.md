# 0085. The pitching minimum applies per matchup, and one the models cannot read fails the build

- Status: accepted
- Date: 2026-10-18
- Spec: [0160-pitching-minimum](../specs/0160-pitching-minimum/design.md) · Issue: #160

## Context

The setting is `statQualificationMinimum: {"statId": 34, "limitValue": 30.0}` in every
head-to-head season from 2021 (spec 0160, C1). It does not say whether 30 outs is per
matchup, or a per-week figure that a longer matchup period scales. ESPN stores the
games-started limit as a per-day rate (ADR 0071), but this value is a round 30, which is 10
innings a week. No side in a longer period is below the scaled minimum either, so the
choice moves nothing (C6). 2020 holds 3,000 outs, a season total, in a rotisserie season
that is not covered.

## Decision drivers

- Read the setting as given, where no evidence argues otherwise.
- A setting the models cannot read is never applied silently (ADR 0071).

## Considered options

1. **Per matchup, as given**; a minimum on any stat but 34, or in a league-season that is
   not head-to-head, fails the build.
2. **Scaled by the period's days over 7**, with the same failures.
3. **Per matchup**, with no failures: an unknown stat is ignored.

## Decision

Chosen by the owner on 2026-10-18: **option 1**. It is the literal reading, it fits the one
case, and it changes no side compared with option 2 (C6). Option 3 would quietly ignore a
minimum the league enforces. A singular test on `stg_espn__league_settings` makes the
failures.

## Consequences

- Good: a league with another kind of minimum stops the build, naming the league-season
  and the setting.
- Bad / accepted cost: if ESPN scales by period length, a long period's side between 30
  and the scaled minimum would be judged wrongly. None exists in six seasons, and the
  reconciliation would show one.
- Follow-ups: revisit if a long-period side ever lands between the two.
