-- Each league-season's first scoring period with a game falls on MLB's opening day of
-- that same season.
--
-- Two independent sources agreeing: the period and its date come from ESPN's own pro
-- schedule (ADR 0023), opening day from MLB's games. That they land on the same date is
-- real evidence the mapping is right. The test also fails for a league-season with no MLB
-- season loaded, for one with no pro schedule, and for one whose first period with a
-- game has no date.
--
-- "The first period with a game", not "period 1". They are the same period in every
-- season but one: in 2020 ESPN kept the numbering of the season as first scheduled, so
-- period 1 is 2020-03-26 and the first game is period 120, on 2020-07-23, MLB's actual
-- first game. The mapping agreed with MLB that year and "period 1 is opening day" did
-- not (spec 0085, amendment of 2026-10-08).
--
-- Compared per season: with two seasons loaded, holding a 2027 league to 2026's opening
-- day (the earliest MLB date of everything loaded) would fail for the wrong reason, or
-- pass for the wrong one.

with first_game_period as (

    select
        season,
        min(scoring_period) as scoring_period
    from {{ ref('stg_espn__pro_games') }}
    group by season

),

fantasy_first_game_day as (

    select
        periods.league_id,
        periods.season,
        periods.scoring_period,
        periods.scoring_date
    from {{ ref('stg_espn__scoring_periods') }} as periods
    inner join first_game_period
        on first_game_period.season = periods.season
        and first_game_period.scoring_period = periods.scoring_period

),

mlb_opening_day as (

    select
        season,
        min(official_date) as official_date
    from {{ ref('stg_mlb__games') }}
    group by season

),

league_seasons as (

    select
        league_id,
        season
    from {{ ref('stg_espn__league_settings') }}

)

-- Driven from the league-seasons, so a missing period, or a season with no MLB games
-- loaded, is a failure rather than a comparison against nothing.
select
    league_seasons.league_id,
    league_seasons.season,
    fantasy_first_game_day.scoring_period,
    fantasy_first_game_day.scoring_date,
    mlb_opening_day.official_date
from league_seasons
left join fantasy_first_game_day
    on fantasy_first_game_day.league_id = league_seasons.league_id
    and fantasy_first_game_day.season = league_seasons.season
left join mlb_opening_day
    on mlb_opening_day.season = league_seasons.season
where
    fantasy_first_game_day.scoring_date is null
    or mlb_opening_day.official_date is null
    or fantasy_first_game_day.scoring_date != mlb_opening_day.official_date
