# 0012. Players have a conformed dimension and a per-league-season table

- Status: accepted, amended by [0033](0033-the-player-dimension-is-one-row-per-mlb-player.md)
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

- `dim_player_league_seasons` (new) has one row per (`platform`, `league_id`, `season`,
  `platform_player_id`). It holds how the player was resolved **in that league-season**
  (`mlbam_player_id`, `player_resolution`, `player_name`) and `default_position`,
  `replacement_group`, `first_rostered_date`, `last_rostered_date` and
  `is_transaction_only`. Every league-season model takes its MLBAM id from here.
- `dim_players` stays one row per (`platform`, `platform_player_id`), its key unchanged,
  with `mlbam_player_id`, `player_resolution` and `player_name` copied from the player's
  latest league-season row. It is a *conformed dimension*: one thing to refer to a player
  by, in any league or season. It is a reference; no league-season number reads from it.

Resolution is per league-season because a design review of the first version found that
a global match lets a later season change an earlier one: a player unresolved in 2026
and matched by name in 2027 would have had his 2026 transactions valued in a combined
build and not in a 2026 build. The name fallback therefore asks whether a name is unique
among the MLB players **of that season**.

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
- Bad / accepted cost: `dim_players` depends on everything loaded: its row is his
  latest league-season's, so it is not the same in a combined build as in a build of one
  league-season alone. That is what conformed means. It is exempt from the isolation
  gate (ADR 0013) by name and held to two invariants instead: it has exactly the players
  of the league-season table, and each row equals the row it is taken from.
- Bad / accepted cost: the same ESPN player could, through a name match, carry different
  MLB ids in different seasons. Each league-season row is right for its season;
  `dim_players` shows the latest.
- Bad / accepted cost: two models to keep in step, tied by a relationships test.
- Bad / accepted cost: the dimension is keyed by the fantasy platform's player id, so it
  is one reference within ESPN, not across platforms. The owner raised keying it by the
  MLB id (2026-10-04). On 2026 that would be clean (498 of 498 players resolve, one to
  one), but it needs a rule for players with no MLB id, a source for MLB player
  attributes, and a decision on who is in the table. It is kept out of #28, which is
  about league and season.
- Follow-ups: #60 keys the dimension by MLB id with a platform bridge. This ADR's split is
  a step toward it: `dim_player_league_seasons` would not change.
