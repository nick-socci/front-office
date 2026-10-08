-- Every game of a scoring period must fall on that period's one Eastern date.
--
-- stg_espn__scoring_periods dates period N as period 1's date plus (N - 1) days, period
-- 1's date being the earliest one any game of the season implies (ADR 0023). That holds
-- only if every game implies the same date: all games of period N start on one
-- US/Eastern date, and period N + 1 is the next date. Any game off that line is returned.
--
-- It also catches a UTC date used in place of the Eastern one: 583 games of 2026 start
-- on a different UTC date than Eastern date, and would land a period late.
--
-- Empty while no pro_schedule capture is loaded (the CI fixtures have none yet).

with period_one as (

    select
        season,
        min(game_date - (scoring_period - 1)::integer) as period_one_date
    from {{ ref('stg_espn__pro_games') }}
    group by season

)

select
    games.season,
    games.espn_game_id,
    games.scoring_period,
    games.game_date,
    period_one.period_one_date + (games.scoring_period - 1)::integer as expected_date
from {{ ref('stg_espn__pro_games') }} as games
inner join period_one
    on games.season = period_one.season
where games.game_date != period_one.period_one_date + (games.scoring_period - 1)::integer
