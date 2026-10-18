-- In every playoff matchup, the home side is the better seed. Returns each playoff matchup
-- whose home seed is not lower in number than the away seed, or where either seed is
-- missing, with both seeds.
--
-- fct_matchup_results gives a level playoff matchup to the home side because ESPN seats the
-- higher seed there (ADRs 0080, 0081): the model reads no seeds, so this test is what holds
-- the assumption. If ESPN ever seats a lower seed at home, the model would give a level
-- matchup to the wrong side, and the build fails here by name instead.
--
-- Seeds are ESPN's playoffSeed in the newest teams capture of the season, so these are the
-- final seeds. Both teams are LEFT joined, so a team with no row in stg_espn__teams reads
-- as a null seed and is returned, not dropped as an inner join would.
--
-- Not in the BigQuery slice: stg_espn__teams is a member-data endpoint not yet in BigQuery
-- (#136), and the slice selects a test only when all its parents are in it.

select
    results.league_id,
    results.season,
    results.matchup_id,
    results.playoff_tier,
    results.home_team_id,
    results.away_team_id,
    home_team.playoff_seed as home_seed,
    away_team.playoff_seed as away_seed
from {{ ref('fct_matchup_results') }} as results
left join {{ ref('stg_espn__teams') }} as home_team
    on home_team.league_id = results.league_id
    and home_team.season = results.season
    and home_team.team_id = results.home_team_id
left join {{ ref('stg_espn__teams') }} as away_team
    on away_team.league_id = results.league_id
    and away_team.season = results.season
    and away_team.team_id = results.away_team_id
where
    results.playoff_tier != 'NONE'
    and (
        home_team.playoff_seed is null
        or away_team.playoff_seed is null
        or home_team.playoff_seed >= away_team.playoff_seed
    )
