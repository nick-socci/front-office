-- Every game a stat line is scored on is in ESPN's pro schedule, on the same scoring period.
--
-- This catches a stat line scored on a period its game is not scheduled on, and a line
-- whose game is not in the schedule at all (scheduled_period comes back null). Either means
-- the schedule and the game lines disagree about which fantasy day a game belongs to, and
-- the dates built from the schedule would be wrong for those lines.
--
-- On the 2026 season all 2,339 distinct (league, season, period, game) pairs pass. In CI it
-- compares the two periods of real ESPN lines in the fixture rosters, which are from the
-- MLB fixture days (ADR 0025). dbt cannot unit-test a singular test, so its two branches (a wrong period, a missing game) are
-- exercised by one-off queries on the real season (spec 0073).

with played as (

    select distinct
        league_id,
        season,
        scoring_period,
        espn_game_id
    from {{ ref('stg_espn__player_game_stats') }}

)

select
    played.league_id,
    played.season,
    played.scoring_period,
    played.espn_game_id,
    pro_games.scoring_period as scheduled_period
from played
left join {{ ref('stg_espn__pro_games') }} as pro_games
    on pro_games.season = played.season
    and pro_games.espn_game_id = played.espn_game_id
where pro_games.espn_game_id is null
   or pro_games.scoring_period != played.scoring_period
