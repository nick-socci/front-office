-- One row per scoring period: the calendar date each fantasy day corresponds to.
--
-- This is the join that makes the whole pipeline useful. ESPN keys rosters by
-- scoringPeriodId; MLB keys game logs by date. Without this mapping the two halves of
-- the warehouse cannot meet.
--
-- ESPN does not publish the mapping: settings.scheduleSettings.matchupPeriods maps
-- matchup period N to [N], which says nothing about days. It is derived instead from an
-- anchor -- the league status recorded with each settings snapshot tells us which period
-- was current when that snapshot was taken -- plus the fact that one scoring period is
-- one calendar day.
--
-- Independent confirmation, from a source ESPN knows nothing about: the anchor implies
-- period 1 = 2026-03-25, which is exactly MLB's opening day in stg_mlb__games. The test
-- stg_espn__scoring_periods_start_on_opening_day.sql keeps checking that.

with anchor as (

    select
        league_id,
        season,
        latest_scoring_period as anchor_period,
        final_scoring_period,
        {{ fo_eastern_date('fetched_at') }} as anchor_date
    from {{ ref('stg_espn__league_settings') }}

),

periods as (

    select
        anchor.league_id,
        anchor.season,
        anchor.anchor_period,
        anchor.anchor_date,
        generate_series as scoring_period
    from anchor,
        -- lateral: each league-season runs to its own final period, not to the longest
        generate_series(1, anchor.final_scoring_period)

)

select
    league_id,
    season,
    scoring_period,
    -- cast: DuckDB defines date +/- INTEGER, not date +/- BIGINT
    anchor_date + ((scoring_period - anchor_period)::integer) as scoring_date
from periods
