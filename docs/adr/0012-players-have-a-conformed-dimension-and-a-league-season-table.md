# 0012. Players have a conformed dimension and a per-league-season table

- Status: proposed
- Date: 2026-10-04
- Spec: [0028-league-season-identity](../specs/0028-league-season-identity/design.md) · Issue: #28

## Context

`dim_players` has one row per platform player id and no league or season. With one
league-season loaded that is unambiguous. With several it is not: most of what is on the
row is read from a roster or a transaction log, and those belong to a league and a
season.

| Column | A fact about |
|---|---|
| `platform_player_id`, `mlbam_player_id`, `player_resolution`, `player_name` | the player |
| `default_position`, `replacement_group` | his latest roster day in one league-season |
| `first_rostered_date`, `last_rostered_date`, `is_transaction_only` | his time in one league-season |

A pitcher can be `SP` one year and `RP` the next, and rostered all season in one league
and never in another. Choosing a grain is the owner's decision.

## Decision drivers

- A row's attributes must all be true at the row's grain.
- The project's stated intent is several seasons and leagues; a player should be one
  thing to refer to across all of them.
- No over-engineering: no more tables than the two grains that exist.
- No value changes for 2026.

## Considered options

1. **One row per (league, season, player)** — the existing columns, keyed by league and
   season as well.
2. **A conformed player dimension plus a per-league-season table** — `dim_players` holds
   what is true of the player everywhere; a second model holds what is true of him in one
   league-season.
3. **One row per player, attributes from his latest appearance anywhere** — the current
   shape, unchanged.

## Decision

Chosen by the owner on 2026-10-04: **option 2**.

- `dim_players` stays one row per (`platform`, `platform_player_id`), its key unchanged,
  and keeps `mlbam_player_id`, `player_resolution` and `player_name`. It is a *conformed
  dimension*: it means the same thing to every fact that joins it, in any league or
  season.
- `dim_player_league_seasons` (new) has one row per (`platform`, `league_id`, `season`,
  `platform_player_id`) and holds `default_position`, `replacement_group`,
  `first_rostered_date`, `last_rostered_date` and `is_transaction_only`.

Option 1 was the recommendation: every column true at its grain with one model. The
owner chose option 2 because the intent is known. Several seasons and leagues are
coming, and a single place to refer to a player, independent of any fantasy league or
season, is worth having from the start; adding it later would mean re-pointing every
fact. Option 3 is wrong as soon as a role changes between seasons.

## Consequences

- Good: one row per player, for good; `dim_players`' key and its uniqueness test do not
  change.
- Good: nothing league-specific is borrowed from another league or year.
- Bad / accepted cost: `dim_players` loses five columns, which move to the new model with
  the same values. A reader of `replacement_group` joins the new model.
- Bad / accepted cost: `dim_players` depends on everything loaded. `player_name` is the
  spelling on his latest roster day in any league, and the name-match resolution judges
  uniqueness over every MLB player loaded, so its rows are not the same in a combined
  build as in a build of one league-season alone. That is what conformed means; the
  isolation gate (ADR 0013) holds on the fixture only because its league-seasons are
  copies.
- Bad / accepted cost: two models to keep in step, tied by a relationships test.
- Follow-ups: none.
