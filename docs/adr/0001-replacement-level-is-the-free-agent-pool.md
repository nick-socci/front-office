# 0001. Replacement level is the free-agent pool

- Status: accepted
- Date: 2026-10-03
- Spec: [0011-player-value](../specs/0011-player-value/design.md) · Issue: #11

## Context

Value over replacement needs a replacement. The original plan used "the median production
of a rostered-but-benched player at the same primary slot". Measured on 2026, that median
is 0 hits and 0 outs in every group: benched starting pitchers appear on 4.0% of bench
days, relievers on 8.7%, hitters on 65.2%. Value over it would be raw production. The
2026-09-27 review asked for exactly this bias check.

The warehouse also holds 44,217 MLB player-days by 1,266 players who were on no fantasy
roster that date.

## Decision drivers

- Replacement should mean something a manager could actually have had.
- The level must not be an artefact of availability (off days, injuries, platoons).
- It must be stable under a reasonable change of its one parameter.
- It must be computable from data already landed.

## Considered options

1. **Free-agent pool** — pooled production of the top N unrostered players per group.
2. **Bench median** — the original plan; optionally restricted to days the player played.
3. **Last rostered starter** — the Nth-best rostered player per position.

## Decision

Chosen: **the free-agent pool**, with three groups (hitter, SP, RP) and N = the number of
fantasy teams (12 in 2026), ranked by playing time while unrostered (plate appearances
for hitters, outs for pitchers). It is the only option that measures availability rather
than a manager's choice, and it is stable: hitters' AVG is .241 / .242 / .242 (the middle figure was first recorded as .237; corrected 2026-10-03) and starters'
ERA 5.07 / 5.15 / 5.00 at N = 6 / 12 / 24, against .254 and 3.81 for started players.

Three groups rather than one per hitter position because 12 free agents split nine ways
is two players a position, and a level set by two players is noise.

## Consequences

- Good: replacement has its usual meaning, and the definition and its sensitivity fit in
  a model header.
- Bad / accepted cost: the pool is players nobody wanted all season. A free agent who got
  hot and was added leaves the pool on that date, so the level is slightly below what an
  alert manager could have found. Catcher scarcity is ignored.
- Bad / accepted cost: relievers are less stable than the other groups (ERA 4.45 / 4.13 /
  3.90 across N).
- Follow-ups: revisit per-position hitter groups if a second season makes the pools
  deep enough.
