# 0034. The league-season table is the bridge, and facts carry the MLB id

- Status: accepted
- Date: 2026-10-09
- Spec: [0060-player-dimension-by-mlb-id](../specs/0060-player-dimension-by-mlb-id/design.md) · Issue: #60

## Context

With `dim_players` keyed by MLB id (ADR 0033), something must say which MLB player a
platform's player id is. #60 asks for "a platform bridge", whether the facts are
re-keyed or resolve through it, and what it means if one ESPN player carries different
MLB ids in different seasons.

A platform player is matched to an MLB player per league-season (#28): the name fallback
depends on that season's MLB players and on the name that league showed. So
`dim_player_league_seasons` already holds the match at the grain it is made. Today's
`dim_players` is that table reduced to one row per platform player by a "latest" rule;
nothing reads it but tests. The three player facts are keyed by `platform_player_id`
and the issue notes that re-keying them risks the 2026 numbers.

## Decision drivers

- Every row true at its grain; no rule that picks one league-season's answer for all.
- No change to a 2026 value.
- A fact should join the player dimension in one step.
- No model without a reader.

## Considered options

For the bridge:

1. **`dim_player_league_seasons` is the bridge; no platform-grain table is kept.**
2. **Keep a platform-grain bridge** (today's `dim_players`, renamed), one row per
   platform player with his latest MLB id.

For the facts:

A. **Keep grain and `platform_player_id`; add `mlbam_player_id`.**
B. **Re-key the facts by MLB id.**
C. **Leave the facts alone**; a query joins through the league-season table.

## Decision

Chosen by the owner on 2026-10-09: **1 and A**.

The path from a platform's player to an MLB player is his row in
`dim_player_league_seasons` for the league-season in question. If one platform player
has different MLB ids in different league-seasons, each is right for its own; both MLB
players have a dimension row, and a warning test names him on every build.

Each of `fct_player_category_value`, `fct_player_season_value` and
`fct_transaction_impact` gains `mlbam_player_id` as its last column, read from its own
league-season's row and null for an unresolved player. Nothing else about them changes.

Option 2 needs the "latest" rule ADR 0012 listed as a cost, to produce a table with no
reader. The owner asked why not keep it: for the 489 players the id map resolves the
mapping is platform-level, and a one-row lookup is convenient; it was still dropped.
Option B changes three grains and their tests to gain what one added column gives, loses an unresolved player's rows, and merges a player a platform splits in two.
Option C leaves every query to make a four-column join before it can name a player.

## Consequences

- Good: no "latest league-season" rule decides an id anywhere.
- Good: a fact joins `dim_players` on one column; its existing columns are untouched.
- Bad / accepted cost: there is no single row for "this ESPN player"; a reader who wants
  one aggregates the league-season table.
- Bad / accepted cost: the facts carry two player ids. The platform's is part of the
  grain; MLB's is an attribute of the row.
- Bad / accepted cost: one warning test more, silent on 2026.
- Follow-ups: later player facts (#12) follow the same convention.
