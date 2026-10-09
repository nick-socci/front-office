# 0035. A player's name and attributes come from MLB's season player list

- Status: accepted
- Date: 2026-10-09
- Spec: [0060-player-dimension-by-mlb-id](../specs/0060-player-dimension-by-mlb-id/design.md) · Issue: #60

## Context

A dimension of MLB players (ADR 0033) needs MLB's attributes for them. #60 names three
sources: the boxscore lines already landed, MLB's people endpoint (new ingestion), and
the third-party id map.

Measured on 2026-10-09:

- Boxscore lines name all 1,472 players with a game, one spelling per id. They carry
  the position played in that game and nothing else about the player.
- MLB's season list (`/api/v1/sports/1/players?season=2026`: public, one request, about
  1.5 MB) holds 1,511 players: the same 1,472 with identical names, 39 with no 2026
  game, and 494 of the 498 players a league resolved. Every row has a primary position,
  batting side, throwing hand and birth date; 21 have no debut date.
- The id map holds 1,209 of the 1,472.
- 4 resolved players are in no list. All 4 have a name from the platform.

## Decision drivers

- A name for every row, from the most authoritative source that has one.
- MLB's own record of a player, landed as raw JSON like every other source.
- Where a name came from should be visible.
- Only attributes true of the player, not of a game or a league-season.

## Considered options

1. **Boxscores already landed; the platform's name where there is no game.** No new
   ingestion, a name only.
2. **Land MLB's season player list** and take names and attributes from it, with the
   boxscore and then the platform as fallback for the name.
3. **The id map's names.**

## Decision

Chosen by the owner on 2026-10-09: **option 2**. The recommendation was option 1,
because the list changes none of the 1,472 names; the owner chose the list for the
attributes it brings.

`dim_players.player_name` is, in order: the name on the player's row of the latest
season's list that holds him; else the name on his latest loaded game line; else the
latest name a league-season shows for him. `name_source` says which (`mlb_players`,
`mlb_boxscore`, `platform`).

The column set, confirmed by the owner on 2026-10-09 (handedness and position only, and
the five plus the current team, were the alternatives): `primary_position`, `bats`,
`throws`, `birth_date` and `mlb_debut_date`, from the same row of the list, null for a player no
list holds. Not taken: team (it changes within a season), height and weight, `active`
(true for every row), and age, which is derived from `birth_date` when asked for.
`fullName` is the only name field read.

Option 3 covers fewer players than the boxscores and is not MLB's own data.

## Consequences

- Good: handedness, birth date, debut and MLB's position for every listed player.
- Good: a player is named from three sources in a stated order, so a missing list
  costs attributes, never a name.
- Good: MLB's spelling, accents included, where ESPN's is stripped.
- Bad / accepted cost: a new endpoint, landing folder, staging model, fixture and audit
  finding, for attributes no model reads yet.
- Bad / accepted cost: `primary_position` is MLB's designation at fetch time, not on a
  date, and has no fantasy meaning.
- Bad / accepted cost: 4 players on 2026 are in no list and have a platform name and
  null attributes; per-player requests would fill them and are not made.
- Follow-ups: [0036](0036-the-player-list-is-a-season-level-snapshot-landed-on-every-mlb-run.md)
  says how the list is captured.
