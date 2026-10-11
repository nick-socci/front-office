-- Every scoring period a matchup period covers is a scoring period of ITS OWN league and
-- season.
--
-- This replaces a single-column `relationships` test on scoring_period, which compared
-- the value alone: with a long season and a short one loaded, a matchup of the short
-- season pointing at a period that exists only in the long one would have passed (#28).
-- Returns the offending rows.
--
-- It reads the two sources of the mapping, not int_fantasy__matchup_periods: that model
-- inner-joins the scoring periods for their dates, so a mapped period with no scoring
-- period of its own is dropped there and could never be returned here (spec 0083,
-- amendment of 2026-10-11).

with mapped as (

    select
        league_id,
        season,
        matchup_period,
        scoring_period,
        'points_by_scoring_period' as mapping_source
    from {{ ref('stg_espn__matchup_periods') }}

    union all

    select
        league_id,
        season,
        matchup_period,
        scoring_period,
        'matchup_day_marker' as mapping_source
    from {{ ref('stg_espn__matchup_days') }}

)

select
    mapped.league_id,
    mapped.season,
    mapped.matchup_period,
    mapped.scoring_period,
    mapped.mapping_source
from mapped
left join {{ ref('stg_espn__scoring_periods') }} as scoring_periods
    on scoring_periods.league_id = mapped.league_id
    and scoring_periods.season = mapped.season
    and scoring_periods.scoring_period = mapped.scoring_period
where scoring_periods.scoring_period is null
