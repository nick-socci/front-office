-- R6.4: no window starts before the first scoring date OF ITS OWN LEAGUE AND SEASON (#28).
-- A pre-season transaction would otherwise open a window over days that have no matchups and
-- no started players. Returns the offending transactions.

with first_dates as (

    select
        platform,
        league_id,
        season,
        min(scoring_date) as first_scoring_date
    from {{ ref('int_fantasy__matchup_periods') }}
    group by platform, league_id, season

)

select
    impact.platform,
    impact.league_id,
    impact.season,
    impact.transaction_id,
    impact.movement,
    impact.transaction_date,
    impact.window_start
from {{ ref('fct_transaction_impact') }} as impact
inner join first_dates
    on first_dates.platform = impact.platform
    and first_dates.league_id = impact.league_id
    and first_dates.season = impact.season
where impact.window_start < first_dates.first_scoring_date
