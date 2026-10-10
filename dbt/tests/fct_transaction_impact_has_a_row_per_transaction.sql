-- R6.1: fct_transaction_impact has exactly one row per row of int_fantasy__transactions,
-- in every league and season. Returns a row, with both counts, for each league-season where
-- they differ. The unique test catches a doubled transaction; this catches one lost or fanned
-- out by a join, and counting per league-season stops one league's surplus covering
-- another's loss (#28).

with impact as (

    select
        platform,
        league_id,
        season,
        count(*) as impact_rows
    from {{ ref('fct_transaction_impact') }}
    group by platform, league_id, season

),

interface as (

    select
        platform,
        league_id,
        season,
        count(*) as transaction_rows
    from {{ ref('int_fantasy__transactions') }}
    group by platform, league_id, season

)

select
    coalesce(impact.platform, interface.platform) as platform,
    coalesce(impact.league_id, interface.league_id) as league_id,
    coalesce(impact.season, interface.season) as season,
    coalesce(impact.impact_rows, 0) as impact_rows,
    coalesce(interface.transaction_rows, 0) as transaction_rows
from impact
full outer join interface
    on interface.platform = impact.platform
    and interface.league_id = impact.league_id
    and interface.season = impact.season
where coalesce(impact.impact_rows, 0) <> coalesce(interface.transaction_rows, 0)
