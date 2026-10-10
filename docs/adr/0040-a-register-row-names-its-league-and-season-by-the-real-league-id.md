# 0040. A register row names its league and season, the league by its real ESPN id

- Status: proposed
- Date: 2026-10-09
- Spec: [0099-register-keyed-by-league-season](../specs/0099-register-keyed-by-league-season/design.md) · Issue: #99

## Context

`espn_reconciliation_residuals`, the register of known differences from ESPN, is keyed by
matchup, team and stat. ESPN restarts matchup and team ids in every league and season, so
a row applies to every league-season at once. Measured on 2026-10-09: 24 of the 31 rows
match a (matchup, team, stat) that exists in the same league's 2025 totals, and three
attach to the fixture league in CI. Only the absence of rosters in the other seasons
keeps this silent. #81 added an alarm, `ambiguous_register`, and ADR 0032 left the fix
as a follow-up.

A key with league and season needs a way to name a league in a file committed to a
public repo, and the league is private. The real league id is already in five tracked
files under `ingestion/tests/` and in five commits. It is not one of the things rule 2
of `AGENTS.md` forbids: those are members' names and ESPN account GUIDs. A private
league's id opens nothing without its members' cookies.

## Decision drivers

- A register row applies to one league-season, and a league-season reads only its own
  rows (ADR 0013).
- General across leagues: a second league needs rows, not setup.
- Joined like every other league-scoped model, on `league_id` and `season`.
- No league member's data in the repo.

## Considered options

1. **The real ESPN league id**, in `league_id`, with `season`.
2. **An alias in the seed and a gitignored mapping** from alias to league id.
3. **A hash of the league id.**
4. **Keep the register in `data/`**, outside the repo.

## Decision

Chosen by the owner on 2026-10-09: **option 1**. The seed's key is
(`league_id`, `season`, `matchup_id`, `team_id`, `stat_id`), `league_id` is the real ESPN
league id as text, and every join to the register uses all five. `ambiguous_register` is
removed.

Option 2 hides in one file an id the tests already state, and adds something every real
build needs and CI cannot check. Option 3 is not private: a five-digit id is found by
hashing every five-digit number. Option 4 takes the project's account of where it
disagrees with ESPN, and the review of each row's evidence, out of the public record.

## Consequences

- Good: the register is keyed like the rest of the warehouse; a second league or season
  adds rows and nothing else.
- Good: in CI no register row applies to a fixture league, where three did by accident.
- Bad / accepted cost: the league id is stated in one more tracked file.
- Bad / accepted cost: in CI every register row is about a league that is not loaded, so
  the joins are exercised there by unit tests alone.
- Bad / accepted cost: a local warehouse needs `dbt seed --full-refresh` once.
- Follow-ups: revisit if a league is added whose id should not be public, or if the
  owner decides to take the id out of `ingestion/tests/`.
