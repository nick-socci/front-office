-- Every scoring period belongs to exactly one matchup period.
--
-- The marts aggregate daily production up to the matchup grain. A day belonging to no
-- matchup silently drops a player's stats out of his team's total; a day belonging to
-- two silently double-counts them. Both produce a number that looks reasonable and does
-- not reconcile, which is the expensive kind of wrong.
--
-- Asserted in this direction on purpose. The reverse -- every day of every matchup has a
-- scoring period -- does not hold on the CI fixtures, which carry two scoring periods and
-- the twelve-day matchup period that contains them.

with per_period as (

    select
        periods.league_id,
        periods.season,
        periods.scoring_period,
        count(matchups.matchup_period) as matchup_periods
    from {{ ref('stg_espn__scoring_periods') }} as periods
    left join {{ ref('stg_espn__matchup_periods') }} as matchups
        on matchups.league_id = periods.league_id
        and matchups.season = periods.season
        and matchups.scoring_period = periods.scoring_period
    group by periods.league_id, periods.season, periods.scoring_period

)

select *
from per_period
where matchup_periods != 1
