-- A drop names the team that had the player.
--
-- Which message field names the acting team depends on the message type (ADR 0004), and
-- the rule is a seed, so a wrong rule would not fail any shape test: every row would
-- still have a team id, just the wrong one. This checks the answer against the rosters.
-- If the player was on some team's roster the day before the drop, that team must be the
-- one the drop names.
--
-- Compared within the drop's own league and season (#28): another league's roster says
-- nothing about this drop.
--
-- Out of scope on purpose: a player on no roster the day before (a pre-season drop, or
-- a same-day add-and-drop) has nothing to compare against.

select
    drops.league_id,
    drops.season,
    drops.transaction_id,
    drops.transaction_date,
    drops.platform_player_id,
    drops.fantasy_team_id as named_team_id,
    rostered.fantasy_team_id as rostering_team_id
from {{ ref('int_fantasy__transactions') }} as drops
inner join {{ ref('int_fantasy__roster_days') }} as rostered
    on rostered.platform = drops.platform
    and rostered.league_id = drops.league_id
    and rostered.season = drops.season
    and rostered.platform_player_id = drops.platform_player_id
    and rostered.scoring_date = drops.transaction_date - 1
where
    drops.movement = 'drop'
    and rostered.fantasy_team_id != drops.fantasy_team_id
