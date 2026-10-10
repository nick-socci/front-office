-- Fails when a team-day with no gain reports a player brought in, sat or moved (R4.8).
--
-- By R3.4 a lineup that differs from the actual one gains at least 1e-9, so a gap below
-- 5e-10 (half of that, to leave room for the order of a floating-point sum) means the
-- optimal lineup is the actual one. This catches churn on a tie: a bench player of equal
-- value swapped in for no gain. It is not R3.2's bound: a changed lineup with a gap between
-- 1e-9 and 1.8e-8 is a correct result and passes. Unvalued rows have a null gap and are
-- not tested.

select
    platform,
    league_id,
    season,
    scoring_date,
    fantasy_team_id,
    value_gap,
    players_brought_in,
    players_sat,
    players_moved
from {{ ref('fct_lineup_decisions') }}
where
    value_gap < 5e-10
    and (players_brought_in > 0 or players_sat > 0 or players_moved > 0)
