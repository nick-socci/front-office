-- Fails when a team-period with no gain reports a player brought in, sat or moved (R4.3).
--
-- By R3.4 a lineup that differs from the actual one gains at least 1e-9, so a period gap
-- below 5e-10 (half of that, to leave room for the order of a floating-point sum) means the
-- optimal lineups are the actual ones. This catches churn on a tie: a bench player of equal
-- value swapped in for no gain. It is not R3.2's bound: a changed lineup with a gap between
-- 1e-9 and 1.8e-8 is a correct result and passes.
--
-- It is judged per team-period (ADR 0092): the optimal lineup is chosen over the matchup
-- period, so a team-day with a zero gap may change players where the period gains, and a
-- team-day's own gap says nothing about whether it should. The gap is the sum of the days'
-- gaps, in date order. Unvalued team-periods have no gap and are not tested.

select
    platform,
    league_id,
    season,
    matchup_period,
    fantasy_team_id,
    {{ fo_sum_in_order('value_gap', 'scoring_date') }} as period_gap,
    sum(players_brought_in) as players_brought_in,
    sum(players_sat) as players_sat,
    sum(players_moved) as players_moved
from {{ ref('fct_lineup_decisions') }}
where not is_unvalued
group by platform, league_id, season, matchup_period, fantasy_team_id
having
    {{ fo_sum_in_order('value_gap', 'scoring_date') }} < 5e-10
    and sum(players_brought_in) + sum(players_sat) + sum(players_moved) > 0
