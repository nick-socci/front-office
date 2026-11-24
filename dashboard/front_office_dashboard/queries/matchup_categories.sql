-- example: {"platform": "espn", "league_id": "111111", "season": 2026, "matchup_id": 1}
-- One matchup's category scores, one row per side and category.
select
    c.category_key,
    c.category_label,
    c.fantasy_team_id,
    t.team_name,
    c.is_home,
    c.team_value,
    c.opponent_value,
    c.result,
    c.is_lower_better,
    c.is_below_minimum,
    c.is_opponent_below_minimum,
    c.has_unverified_inputs
from marts.fct_matchup_category_scores as c
inner join marts.dim_fantasy_teams as t
    on
        c.platform = t.platform
        and c.league_id = t.league_id
        and c.season = t.season
        and c.fantasy_team_id = t.fantasy_team_id
where
    c.platform = $platform and c.league_id = $league_id and c.season = $season
    and c.matchup_id = $matchup_id
order by c.category_key, c.is_home desc
