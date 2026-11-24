-- example: {"platform": "espn", "league_id": "111111", "season": 2026}
-- Standings (ADR 0148): a completed regular season is in ESPN's seed order; one in progress is
-- ordered by the computed record so far. The computed and the reported records sit side by side.
select
    s.fantasy_team_id,
    t.team_name,
    s.scoring_type,
    s.is_regular_season_complete,
    s.matchups,
    s.wins,
    s.losses,
    s.ties,
    s.reported_wins,
    s.reported_losses,
    s.reported_ties,
    s.reported_playoff_seed,
    s.category_wins,
    s.category_losses,
    s.category_ties
from marts.fct_team_standings as s
inner join marts.dim_fantasy_teams as t
    on
        s.platform = t.platform
        and s.league_id = t.league_id
        and s.season = t.season
        and s.fantasy_team_id = t.fantasy_team_id
where s.platform = $platform and s.league_id = $league_id and s.season = $season
order by
    case when s.is_regular_season_complete then s.reported_playoff_seed end nulls last,
    s.wins desc,
    s.losses asc,
    t.team_name
