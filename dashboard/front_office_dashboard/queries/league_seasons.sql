-- The league-season picker on every page: every league-season the extract holds.
select distinct platform, league_id, season
from marts.dim_fantasy_teams
order by season desc, league_id, platform
