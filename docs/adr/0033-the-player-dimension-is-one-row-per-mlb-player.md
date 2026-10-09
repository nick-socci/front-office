# 0033. The player dimension is one row per MLB player

- Status: accepted
- Date: 2026-10-09
- Spec: [0060-player-dimension-by-mlb-id](../specs/0060-player-dimension-by-mlb-id/design.md) · Issue: #60
- Amends: [0012](0012-players-have-a-conformed-dimension-and-a-league-season-table.md)

## Context

ADR 0012 made `dim_players` one row per fantasy platform player id and recorded the
cost: it is one reference within ESPN, not across platforms. The owner raised keying it
by MLB id on 2026-10-04, and #60 carries the questions that left open: the key of a
player with no MLB id, and who is in the table.

Measured on 2026: 498 platform players resolve to 498 distinct MLB ids, one to one. The
game logs hold 1,472 MLB players; 979 are in no dimension, and 1,436 have played days on
which nobody rostered them, which is what the replacement pools are made of. 5 rostered
players have no 2026 game. In the CI fixtures 7 transaction-only players have no MLB id.

## Decision drivers

- All production is measured by MLB id; the key should be the one the numbers carry.
- A row's key must not change when the id map catches up with a player.
- A player the warehouse holds production for should have a name, rostered or not.
- No invented identities.

## Considered options

1. **One row per MLB id, for every MLB player loaded plus every resolved id; no row for
   a player with no MLB id.**
2. **One row per MLB id, only for players a league touched.**
3. **A composite key** (`mlb:<id>`, else `espn:<id>`), so an unresolved player has a row.
4. **A placeholder row** per unresolved platform player, under a negative or hashed id.
5. **Keep ADR 0012's key.**

## Decision

Chosen by the owner on 2026-10-09: **option 1**.

`dim_players` has one row per `mlbam_player_id` that appears in a landed MLB player list
(ADR 0035), in the loaded MLB game logs, or as the resolved id of any league-season's
player: 1,515 on 2026. A platform player with no MLB id
has no row; he stays in `dim_player_league_seasons` as `unresolved`, where a warning
test already names him.

Option 2 is today's 498 rows under a new key and leaves the replacement pools nameless.
Options 3 and 4 give an unresolved player a key that changes, or disappears, the day he
is resolved, and make every join carry the special case. Option 5 keeps every future
mart on ESPN's key.

## Consequences

- Good: one reference to a player across platforms, leagues and seasons, and for free
  agents.
- Good: the key is an id the facts already hold; no surrogate to generate or keep stable.
- Bad / accepted cost: an unresolved player cannot be joined to the dimension. None on
  2026; 7 in CI.
- Bad / accepted cost: the table is still defined over everything loaded, so it stays
  exempt by name from the isolation gate (ADR 0013) and is held to its own tests.
- Bad / accepted cost: 1,515 rows where there were 498, most of them players no league
  touched.
- Amends ADR 0012: its `dim_players` key and "latest league-season" rule are replaced.
  Its split into a player table and a league-season table stands, and
  `dim_player_league_seasons` does not change.
- Follow-ups: #12 builds its mart on this key.
