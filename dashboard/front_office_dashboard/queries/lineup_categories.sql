-- example: {"platform": "espn", "league_id": "111111", "season": 2026, "fantasy_team_id": 9}
-- One team's category results per matchup, as played against as the best lineup would have.
select
    c.matchup_period,
    c.matchup_id,
    c.opponent_team_id,
    o.team_name as opponent_team_name,
    c.category_key,
    c.category_label,
    c.is_lower_better,
    c.actual_value,
    c.opponent_value,
    c.actual_result,
    c.optimal_value,
    c.optimal_result,
    c.has_unverified_inputs
from marts.fct_lineup_decision_categories as c
inner join marts.dim_fantasy_teams as o
    on
        c.platform = o.platform
        and c.league_id = o.league_id
        and c.season = o.season
        and c.opponent_team_id = o.fantasy_team_id
where
    c.platform = $platform and c.league_id = $league_id and c.season = $season
    and c.fantasy_team_id = $fantasy_team_id
order by c.matchup_period, c.matchup_id, c.category_key
