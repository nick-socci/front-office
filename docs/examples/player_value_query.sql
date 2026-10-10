-- Which players were worth the most to the team that started them?
--
-- fct_player_season_value has one row per player and fantasy team: what he produced on
-- the days that team started him, measured against a replacement-level free agent and
-- summed over the league's scoring categories. Its unit is a matchup margin: a
-- total_value of 10 is ten typical category margins over the season (ADR 0010).
--
-- A player's name is not on the fact. Facts carry mlbam_player_id, and dim_players is
-- the one place a player's name and attributes live (ADR 0033), so the name is joined
-- in here.
--
-- Run with:
--   duckdb data/warehouse.duckdb < docs/examples/player_value_query.sql
--
-- Teams are shown by id: fantasy teams' names are their owners' and are left out of
-- anything committed here. Players are major leaguers, and their names are public.

.mode box

select
    player_values.season,
    players.player_name,
    players.primary_position,
    player_values.fantasy_team_id,
    player_values.started_days,
    player_values.played_started_days,
    round(player_values.total_value, 2) as total_value
from marts.fct_player_season_value as player_values
inner join marts.dim_players as players
    on players.mlbam_player_id = player_values.mlbam_player_id
order by player_values.total_value desc, players.player_name
limit 15;
