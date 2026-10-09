# 0035. A player's name comes from the boxscores already landed

- Status: proposed
- Date: 2026-10-09
- Spec: [0060-player-dimension-by-mlb-id](../specs/0060-player-dimension-by-mlb-id/design.md) · Issue: #60

## Context

A dimension of MLB players (ADR 0033) needs MLB's attributes for them. #60 names three
sources: the boxscore lines already landed, MLB's people endpoint (new ingestion), and
the third-party id map.

Measured on 2026-10-09:

- Boxscore lines name all 1,472 players with a game, one spelling per id.
- MLB's season list (`/api/v1/sports/1/players?season=2026`: public, one request) holds
  1,511 players: the same 1,472 with identical names, and 1 of the 5 rostered players
  who have no 2026 game. It also has handedness, birth date, debut date and primary
  position.
- The id map holds 1,209 of the 1,472.
- All 5 players with no game have a name from the platform.

## Decision drivers

- A name for every row, from the most authoritative source that has one.
- No ingestion, fixtures and staging for attributes nothing reads.
- Where a name came from should be visible.

## Considered options

1. **Boxscores already landed; the platform's name where there is no game.**
2. **Land MLB's season player list** and take names and other attributes from it.
3. **The id map's names.**

## Decision

Recommended, for the owner to decide: **option 1**.

`dim_players.player_name` is the name on the player's latest loaded game; with no game,
the name on his latest league-season row; `name_source` says which (`mlb`, `platform`).
The dimension holds no other attribute.

Option 2 changes none of the 1,472 names and adds one of the five missing ones, for a
new endpoint, landing folder, staging model and fixture set. Option 3 covers fewer
players than the boxscores and is not MLB's own data.

## Consequences

- Good: no new source; the dimension is built from what every build already reads.
- Good: MLB's spelling, accents included, where ESPN's is stripped (37 of 493 differ).
- Bad / accepted cost: a player with no loaded game is named by the platform: 5 on 2026,
  289 of 363 in the CI fixtures, which hold few boxscores.
- Bad / accepted cost: no handedness, age or primary position. Nothing reads them yet.
- Bad / accepted cost: a name can change when a later game spells it differently.
- Follow-ups: if an attribute beyond a name is wanted, land the season player list
  (option 2) as its own issue; this decision is then revisited for names too.
