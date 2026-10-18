# 0082. A tie rule the models do not know fails the build

- Status: proposed
- Date: 2026-10-18
- Spec: [0159-playoff-tiebreak](../specs/0159-playoff-tiebreak/design.md) · Issue: #159

## Context

ESPN settings hold two tie rules: `scoringSettings.playoffMatchupTieRule` for playoff
matchups and `scoringSettings.matchupTieRule` for the regular season. Every covered
league-season has `NONE` for both (spec 0159, C4). ADR 0080 models what `NONE` means: a
level playoff matchup goes to the higher seed, and a level regular-season matchup is a tie.
What ESPN's other values do is not documented and is not in the data. A league that sets
one would have its level matchups decided by a rule the models do not apply.

## Decision drivers

- A league setting the models cannot read is never applied silently (ADR 0071's rule for
  an unknown games-started limit).
- Generality across leagues: the models must not assume this league's settings.

## Considered options

1. **Fail the build** when a covered league-season has a tie rule that isn't `NONE`, or
   has none, naming the league-season and both values.
2. **Apply `NONE`'s rule anyway**: every playoff tie goes to the higher seed whatever the
   setting.
3. **Leave such a matchup `TIE`**, as before this spec.

## Decision

Chosen by the owner on 2026-10-18, as recommended: **option 1**, because options 2 and 3
each produce a winner the league may not have had, without saying so. A singular test on
`stg_espn__league_settings`, which now stages both rules, fails the build. Settling what
the other values mean is left to the spec that meets them.

## Consequences

- Good: a league with another tie rule stops the build, and the message says which rule.
- Bad / accepted cost: such a league cannot be built until its rule is modelled.
- Follow-ups: when a league sets one, find what it means from that league's results, as
  spec 0159 did for `NONE`.
