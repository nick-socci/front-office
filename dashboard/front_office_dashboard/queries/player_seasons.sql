-- example: {"mlbam_player_id": 668939}
-- A player's total_value in every season (and league) in which he was started.
select
    s.platform,
    s.league_id,
    s.season,
    s.fantasy_team_id,
    t.team_name,
    s.started_days,
    s.total_value
from marts.fct_player_season_value as s
left join marts.dim_fantasy_teams as t
    on
        s.platform = t.platform
        and s.league_id = t.league_id
        and s.season = t.season
        and s.fantasy_team_id = t.fantasy_team_id
where s.mlbam_player_id = $mlbam_player_id
order by s.season desc, s.league_id, s.fantasy_team_id
