-- Each league-season's fantasy scoring period 1 is MLB's opening day of that same season.
--
-- Two independent sources agreeing again: period 1 comes from ESPN's own pro schedule
-- (ADR 0023), opening day from MLB's games. That they land on the same date is real
-- evidence the mapping is right. The test also fails for a league-season with no MLB season
-- loaded (whether that becomes a warning is left to #57) and for one with no period 1.
--
-- Compared per season: with two seasons loaded, holding a 2027 league to 2026's opening
-- day (the earliest MLB date of everything loaded) would fail for the wrong reason, or
-- pass for the wrong one.

with fantasy_day_one as (

    select
        league_id,
        season,
        scoring_date
    from {{ ref('stg_espn__scoring_periods') }}
    where scoring_period = 1

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

-- Driven from the league-seasons, so a missing period 1, or a season with no MLB games
-- loaded, is a failure rather than a comparison against nothing.
select
    league_seasons.league_id,
    league_seasons.season,
    fantasy_day_one.scoring_date,
    mlb_opening_day.official_date
from league_seasons
left join fantasy_day_one
    on fantasy_day_one.league_id = league_seasons.league_id
    and fantasy_day_one.season = league_seasons.season
left join mlb_opening_day
    on mlb_opening_day.season = league_seasons.season
where fantasy_day_one.scoring_date is null
   or mlb_opening_day.official_date is null
   or fantasy_day_one.scoring_date != mlb_opening_day.official_date
