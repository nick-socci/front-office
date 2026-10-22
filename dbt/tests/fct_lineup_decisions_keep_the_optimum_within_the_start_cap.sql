-- Fails when a team-period's optimal lineup starts more pitchers than the cap allows (R3.4).
--
-- The optimal lineup is chosen per matchup period within a cap on its pitcher starts
-- (ADR 0090): the whole number of starts the league's limit allows, or the starts the actual
-- lineup fielded if that is more, since the actual lineup is itself a legal lineup and an
-- optimum may not be worse than it. If the optimal lineup starts more than that, the
-- limit was not honoured when the lineup was chosen, and credit would silently cut the
-- surplus off afterwards (the fault ADR 0090 supersedes ADR 0079 to remove).
--
-- measured is the optimal lineup's starts over the period, cap the most it may have. The cap
-- is floor(start_limit): a limit that is not a whole number admits only the whole starts
-- below it (spec 0152 leaves open how ESPN rounds). A league-season with no limit
-- (a null start_limit) has no cap and is not tested; neither is an unvalued team-period,
-- which has no optimal lineup (ADR 0092).

with team_periods as (

    select
        platform,
        league_id,
        season,
        matchup_period,
        fantasy_team_id,
        sum(optimal_pitcher_starts) as optimal_starts,
        sum(actual_pitcher_starts) as actual_starts
    from {{ ref('fct_lineup_decisions') }}
    where not is_unvalued
    group by platform, league_id, season, matchup_period, fantasy_team_id

)

select
    team_periods.platform,
    team_periods.league_id,
    team_periods.season,
    team_periods.matchup_period,
    team_periods.fantasy_team_id,
    team_periods.optimal_starts as measured,
    greatest(floor(limits.start_limit), team_periods.actual_starts) as cap
from team_periods
inner join {{ ref('int_fantasy__start_limits') }} as limits
    on limits.platform = team_periods.platform
    and limits.league_id = team_periods.league_id
    and limits.season = team_periods.season
    and limits.matchup_period = team_periods.matchup_period
where
    limits.start_limit is not null
    and team_periods.optimal_starts
    > greatest(floor(limits.start_limit), team_periods.actual_starts)
