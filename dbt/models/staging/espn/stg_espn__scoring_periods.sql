-- One row per scoring period: the calendar date each fantasy day corresponds to.
--
-- This is the join that makes the whole pipeline useful. ESPN keys rosters by
-- scoringPeriodId; MLB keys game logs by date. Without this mapping the two halves of
-- the warehouse cannot meet.
--
-- ESPN's pro schedule is the rule (ADR 0023, superseding ADR 0021). Every scheduled game
-- carries its scoring period and, in stg_espn__pro_games, its Eastern date, so each game
-- implies a date for period 1: its date minus its period plus one. The test
-- stg_espn__pro_games_fall_on_one_date_per_scoring_period fails the build unless they all
-- agree, so the model takes the one date they share, and a period with no game needs no
-- special case: one scoring period is one calendar day, so period N is N-1 days after
-- period 1. The settings capture supplies only the number of periods (final_scoring_period).
--
-- Why not count back from the settings capture's status.latestScoringPeriod: ESPN's
-- counter stops after the season. Five settings captures of 2026 carry counters 186, 186,
-- 188, 188, 188 against a final period of 180; the last two, fetched on later days, imply
-- period 1 = 2026-04-02 and 2026-04-03 instead of 2026-03-25. A date that depends on when
-- a capture was taken is wrong. Nor does the model read latest_scoring_period or
-- fetched_at at all.
--
-- The model reads only ESPN again: the cross-source exception that #70 introduced, reading
-- MLB's games, is gone. What checks it from outside is MLB: its opening day
-- (stg_espn__scoring_periods_start_on_opening_day) and its games per date
-- (stg_espn__scoring_periods_agree_with_espn_game_lines).

with league_seasons as (

    select
        league_id,
        season,
        final_scoring_period
    from {{ ref('stg_espn__league_settings') }}

),

period_one as (

    -- every game implies a date for period 1; a test holds them to one
    select
        season,
        min(game_date - ((scoring_period - 1)::integer)) as period_one_date
    from {{ ref('stg_espn__pro_games') }}
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

-- left join: a league-season with no pro schedule loaded keeps its rows, with a null date,
-- so the not_null test fails instead of downstream models building empty
select
    periods.league_id,
    periods.season,
    periods.scoring_period,
    -- cast: DuckDB defines date +/- INTEGER, not date +/- BIGINT
    period_one.period_one_date + ((periods.scoring_period - 1)::integer) as scoring_date
from periods
left join period_one
    on period_one.season = periods.season
