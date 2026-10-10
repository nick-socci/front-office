-- R5.2: the started days in fct_player_season_value must add back up to the rows of
-- int_fantasy__started_player_days, and inside-matchup days plus outside-matchup days must
-- equal the same total (ADR 0006). Returns one row if either differs.
--
-- Inside is counted here straight from the grain joined to int_fantasy__matchup_periods and then to the team's side in that period (a team with no side that period, a bye, is outside);
-- outside is the fact's own started_days_outside_matchups. So a day lost between the grain
-- and the fact, a day counted in both or neither, or a date in two matchup periods, shows.

with grain as (

    select count(*) as grain_days
    from {{ ref('int_fantasy__started_player_days') }}

),

inside as (

    select count(*) as inside_days
    from {{ ref('int_fantasy__started_player_days') }} as days
    inner join {{ ref('int_fantasy__matchup_periods') }} as periods
        on periods.platform = days.platform
        and periods.league_id = days.league_id
        and periods.season = days.season
        and periods.scoring_date = days.scoring_date
    inner join {{ ref('int_fantasy__matchup_sides') }} as sides
        on sides.platform = periods.platform
        and sides.league_id = periods.league_id
        and sides.season = periods.season
        and sides.matchup_period = periods.matchup_period
        and sides.fantasy_team_id = days.fantasy_team_id

),

fact as (

    select
        coalesce(sum(started_days), 0) as fact_started_days,
        coalesce(sum(started_days_outside_matchups), 0) as outside_days
    from {{ ref('fct_player_season_value') }}

)

select
    grain.grain_days,
    fact.fact_started_days,
    inside.inside_days,
    fact.outside_days
from grain
cross join inside
cross join fact
where
    fact.fact_started_days <> grain.grain_days
    or inside.inside_days + fact.outside_days <> grain.grain_days
