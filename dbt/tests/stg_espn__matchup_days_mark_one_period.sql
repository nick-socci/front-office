-- Every loaded matchup_days response marks exactly one matchup period.
--
-- stg_espn__matchup_days keeps a row only where ESPN put `rosterForCurrentScoringPeriod`
-- on a matchup side. A response that marked nothing would drop out of the model without
-- a trace, and one that marked two periods would map a scoring period twice (ADR 0055).
-- This starts from the newest capture of each scoring period, so the first case is
-- visible, and returns each one for which the model has no row, or more than one.
--
-- The capture view's `schedule` is projected away in `header` and the model is joined on
-- the small columns.

with latest as (

    {{ fo_espn_latest('matchup_days', extra_partition='scoringPeriodId') }}

),

header as (

    select
        league_id,
        season,
        {{ fo_request_param('request_key', 'scoringPeriodId') }} as scoring_period
    from latest

),

marked as (

    select
        header.league_id,
        header.season,
        header.scoring_period,
        count(days.matchup_period) as matchup_periods
    from header
    left join {{ ref('stg_espn__matchup_days') }} as days
        on days.league_id = header.league_id
        and days.season = header.season
        and days.scoring_period = header.scoring_period
    group by header.league_id, header.season, header.scoring_period

)

select *
from marked
where matchup_periods != 1
