-- One row per scoring period: the calendar date each fantasy day corresponds to.
--
-- This is the join that makes the whole pipeline useful. ESPN keys rosters by
-- scoringPeriodId; MLB keys game logs by date. Without this mapping the two halves of
-- the warehouse cannot meet.
--
-- Nothing landed from ESPN gives the mapping: settings.scheduleSettings.matchupPeriods
-- maps matchup period N to [N], which says nothing about days. (ESPN's pro schedule does
-- give it, and is not landed: #73.) One scoring period is one calendar day and period 1
-- is MLB's regular-season opening day, so period N is N-1 days later (ADR 0021).
--
-- Why not count back from the settings capture's status.latestScoringPeriod: ESPN's
-- counter stops after the season. Five settings captures of 2026 carry counters 186, 186,
-- 188, 188, 188 against a final period of 180; the last two, fetched on later days, imply
-- period 1 = 2026-04-02 and 2026-04-03 instead of 2026-03-25. A date that depends on when
-- a capture was taken is wrong. The settings capture supplies only the number of periods
-- (final_scoring_period).
--
-- This is the one staging model that reads another source's staging model
-- (stg_mlb__games). That is deliberate: its whole job is the bridge between the two
-- sources. If issue #73 makes ESPN's own schedule the rule, the model reads only ESPN
-- again and the exception ends.
--
-- The mapping is checked against ESPN's game lines by
-- stg_espn__scoring_periods_agree_with_espn_game_lines.

with league_seasons as (

    select
        league_id,
        season,
        final_scoring_period
    from {{ ref('stg_espn__league_settings') }}

),

opening_days as (

    select
        season,
        min(official_date) as opening_day
    from {{ ref('stg_mlb__games') }}
    where game_type = 'R'
    group by season

),

periods as (

    select
        league_seasons.league_id,
        league_seasons.season,
        generate_series as scoring_period
    from league_seasons,
        -- lateral: each league-season runs to its own final period, not to the longest
        generate_series(1, league_seasons.final_scoring_period)

)

-- left join: a league-season with no MLB season loaded keeps its rows, with a null date,
-- so the not_null test fails instead of downstream models building empty
select
    periods.league_id,
    periods.season,
    periods.scoring_period,
    -- cast: DuckDB defines date +/- INTEGER, not date +/- BIGINT
    opening_days.opening_day + ((periods.scoring_period - 1)::integer) as scoring_date
from periods
left join opening_days
    on opening_days.season = periods.season
