-- example: {"platform": "espn", "league_id": "111111", "season": 2026}
-- The teams of one league-season, for the team pickers and filters.
select fantasy_team_id, team_name, team_abbrev
from marts.dim_fantasy_teams
where platform = $platform and league_id = $league_id and season = $season
order by team_name, fantasy_team_id
