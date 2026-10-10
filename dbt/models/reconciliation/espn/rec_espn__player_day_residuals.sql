-- One row per (league-season, matchup, side, stat) that has a player-day difference: what
-- those differences add up to, what the register of known residuals says they should, and
-- what is wrong if the two do not agree. The register (espn_reconciliation_residuals) is
-- looked up by league, season, matchup, side and stat, so a key is judged only against its
-- own league-season's row. The rule behind the singular test
-- rec_espn__player_day_differences_are_registered, held here so that a unit test can reach
-- it (dbt can unit-test a model and not a singular test; see rec_fantasy__category_wins_by_group).
--
-- Only rows with status = 'difference' are counted. An unverified row compares a number
-- that may be zero only because its boxscore is not loaded, so it can neither need a
-- register row nor make one wrong (ADR 0032).
--
-- problem is, in this order:
--   unregistered        the key has no register row. This is the rule on the key and not on
--                       the sum: differences that cancel, one player credited a hit ESPN
--                       does not have and another the reverse, leave the side's total
--                       matching, and are still differences.
--   wrong_size          the sum differs from the registered difference by more than 1e-9.
--   null                the register accounts for the key.
--
-- It runs one way: from the player-days to the register. A register row with no player-day
-- rows (an inconsistent ESPN total, or a stat this table does not compare) is not returned;
-- rec_espn__matchup_stat_differences already fails on a stale register row.

-- A view, so that the test judges the table as it is now and not as it was last built.
{{ config(materialized='view') }}

with differences as (

    select
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        stat_id,
        difference
    from {{ ref('rec_espn__player_day_differences') }}
    where status = 'difference'

),

keys as (

    select
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        stat_id,
        -- In a fixed order, as every floating-point sum here is.
        sum(difference order by difference) as difference_sum,
        count(*) as difference_rows
    from differences
    group by league_id, season, matchup_id, fantasy_team_id, stat_id

),

register as (

    select * from {{ ref('espn_reconciliation_residuals') }}

)

select
    keys.league_id,
    keys.season,
    keys.matchup_id,
    keys.fantasy_team_id,
    keys.stat_id,
    keys.difference_sum,
    keys.difference_rows,
    register.expected_difference,
    case
        when register.expected_difference is null then 'unregistered'
        when abs(keys.difference_sum - register.expected_difference) > 1e-9 then 'wrong_size'
    end as problem
from keys
left join register
    on register.league_id = keys.league_id
    and register.season = keys.season
    and register.matchup_id = keys.matchup_id
    and register.team_id = keys.fantasy_team_id
    and register.stat_id = keys.stat_id
