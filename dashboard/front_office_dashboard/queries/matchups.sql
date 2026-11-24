-- example: {"platform": "espn", "league_id": "111111", "season": 2026, "matchup_period": 1}
-- Each matchup of one period with both teams' names.
select
    r.matchup_id,
    r.matchup_period,
    r.playoff_tier,
    r.home_team_id,
    h.team_name as home_team_name,
    r.away_team_id,
    a.team_name as away_team_name,
    r.scored_categories,
    r.home_category_wins,
    r.away_category_wins,
    r.category_ties,
    r.categories_undecided,
    r.winner,
    r.is_decided_by_tiebreak,
    r.has_unverified_inputs
from marts.fct_matchup_results as r
inner join marts.dim_fantasy_teams as h
    on
        r.platform = h.platform
        and r.league_id = h.league_id
        and r.season = h.season
        and r.home_team_id = h.fantasy_team_id
inner join marts.dim_fantasy_teams as a
    on
        r.platform = a.platform
        and r.league_id = a.league_id
        and r.season = a.season
        and r.away_team_id = a.fantasy_team_id
where
    r.platform = $platform and r.league_id = $league_id and r.season = $season
    and r.matchup_period = $matchup_period
order by r.matchup_id
