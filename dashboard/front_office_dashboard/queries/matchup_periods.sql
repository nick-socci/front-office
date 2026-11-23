-- example: {"platform": "espn", "league_id": "111111", "season": 2026}
-- The matchup periods of one league-season, for the Matchups page's picker.
select distinct matchup_period
from marts.fct_matchup_results
where platform = $platform and league_id = $league_id and season = $season
order by matchup_period
