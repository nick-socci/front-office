-- example: {"platform": "espn", "league_id": "111111", "season": 2026}
-- The season's players by total_value, with the team that started them and their group.
select
    s.platform_player_id,
    s.mlbam_player_id,
    d.player_name,
    d.default_position,
    d.replacement_group,
    s.fantasy_team_id,
    t.team_name,
    s.started_days,
    s.played_started_days,
    s.started_days_outside_matchups,
    s.unverified_started_days,
    s.first_started_date,
    s.last_started_date,
    s.total_value
from marts.fct_player_season_value as s
left join marts.dim_player_league_seasons as d
    on
        s.platform = d.platform
        and s.league_id = d.league_id
        and s.season = d.season
        and s.platform_player_id = d.platform_player_id
left join marts.dim_fantasy_teams as t
    on
        s.platform = t.platform
        and s.league_id = t.league_id
        and s.season = t.season
        and s.fantasy_team_id = t.fantasy_team_id
where s.platform = $platform and s.league_id = $league_id and s.season = $season
order by s.total_value desc nulls last, d.player_name, s.platform_player_id, s.fantasy_team_id
