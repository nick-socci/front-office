-- example: {"mlbam_player_id": 668939}
-- A player's every league-season in the extract, with his total_value where he was started. The
-- dimension drives it: fct_player_season_value has rows only where he started, so a season he
-- was rostered or transacted but never started shows a null team and value, not no row.
select
    d.platform,
    d.league_id,
    d.season,
    s.fantasy_team_id,
    t.team_name,
    d.first_rostered_date,
    d.last_rostered_date,
    d.is_transaction_only,
    s.started_days,
    s.total_value
from marts.dim_player_league_seasons as d
left join marts.fct_player_season_value as s
    on
        d.platform = s.platform
        and d.league_id = s.league_id
        and d.season = s.season
        and d.platform_player_id = s.platform_player_id
left join marts.dim_fantasy_teams as t
    on
        s.platform = t.platform
        and s.league_id = t.league_id
        and s.season = t.season
        and s.fantasy_team_id = t.fantasy_team_id
where d.mlbam_player_id = $mlbam_player_id
order by d.season desc, d.league_id, s.fantasy_team_id, d.platform_player_id
