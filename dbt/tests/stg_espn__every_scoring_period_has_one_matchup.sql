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

--
-- For league-seasons with rosters (ADR 0026). The mapping exists to assign roster days to
-- matchups, and ESPN does not always publish it: its 2021 matchups carry no per-day
-- breakdown, so that season has no matchup periods here at all. That costs nothing while
-- the season has no roster days to assign; once it has, it is covered and this fails.

with per_period as (

    select
        periods.league_id,
        periods.season,
        periods.scoring_period,
        count(matchups.matchup_period) as matchup_periods
    from {{ ref('stg_espn__scoring_periods') }} as periods
    inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
        on league_seasons.platform = 'espn'
        and league_seasons.league_id = periods.league_id
        and league_seasons.season = periods.season
        and league_seasons.has_rosters
    left join {{ ref('stg_espn__matchup_periods') }} as matchups
        on matchups.league_id = periods.league_id
        and matchups.season = periods.season
        and matchups.scoring_period = periods.scoring_period
    group by periods.league_id, periods.season, periods.scoring_period

)

select *
from per_period
where matchup_periods != 1
