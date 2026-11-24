-- example: {"platform": "espn", "league_id": "111111", "season": 2026, "platform_player_id": 42178}
-- One player's value in each scored category of the season, by team that started them.
select
    c.category_key,
    c.category_label,
    c.fantasy_team_id,
    t.team_name,
    c.is_lower_better,
    c.played_days,
    c.numerator,
    c.denominator,
    c.contribution,
    c.value_over_replacement,
    c.scaled_value
from marts.fct_player_category_value as c
left join marts.dim_fantasy_teams as t
    on
        c.platform = t.platform
        and c.league_id = t.league_id
        and c.season = t.season
        and c.fantasy_team_id = t.fantasy_team_id
where
    c.platform = $platform and c.league_id = $league_id and c.season = $season
    and c.platform_player_id = $platform_player_id
order by c.category_key, c.fantasy_team_id
