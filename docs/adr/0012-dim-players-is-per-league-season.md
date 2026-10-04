# 0012. dim_players has one row per player per league-season

- Status: proposed
- Date: 2026-10-04
- Spec: [0028-league-season-identity](../specs/0028-league-season-identity/design.md) · Issue: #28

## Context

`dim_players` has one row per platform player id and no league or season. With one
league-season loaded that is unambiguous. With several it is not: every attribute on the
row except the MLBAM id is read from a roster or a transaction log, and those belong to
a league and a season. `default_position` and so `replacement_group` come from his
latest roster day; `first_rostered_date`, `last_rostered_date` and `is_transaction_only`
describe his time in one league.

Choosing a grain is the owner's decision.

## Decision drivers

- A row's attributes must all be true at the row's grain.
- Facts join it on keys they already carry.
- A league-season built together with others must give the rows it gives alone.
- No number changes for 2026.

## Considered options

1. **One row per (league, season, player)** — the existing columns, keyed by league and
   season as well.
2. **One row per player, plus a per-league-season table** — a conformed player dimension
   (id, MLBAM id, name) and a second model for position, group and roster dates.
3. **One row per player, attributes from his latest appearance anywhere** — the current
   shape, unchanged.

## Decision

Chosen: **one row per (league, season, player)**. Every column keeps its meaning, the
facts already carry league and season, and the 2026 table is the same 498 rows with two
more columns.

Option 2 is the textbook shape, a *conformed dimension* being one that means the same
thing to every fact that joins it, and it is what following a player across seasons
would want. Nothing needs that yet, and it doubles the models to keep in step. Option 3
is wrong as soon as a pitcher is `SP` in one season and `RP` the next: a drop in 2025
would be valued on his 2026 group, and a combined build would differ from a build alone.

## Consequences

- Good: no attribute is borrowed from another league or year.
- Bad / accepted cost: a player rostered in two leagues, or two seasons, has two rows;
  "one row per player" is no longer true and a join on player id alone fans out. The
  uniqueness test moves to the full key so that mistake fails.
- Bad / accepted cost: there is no single place to look a player up across seasons.
- Follow-ups: a conformed player dimension when a cross-season question arrives.
