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
-- A key is carried when ESPN's own matchup lines agree with its daily lines about the
-- side (ADR 0077, spec 0147): our side value of the key's component, less the key's
-- difference sum, equals the sum of ESPN's matchup lines for that side and stat
-- (rec_espn__matchup_line_totals), within 1e-9. ESPN's daily game lines and its matchup
-- lines are two records of what it credited; when they differ from ours by the same amount
-- the difference is ESPN's own, not a crediting rule we lack. A key whose daily line holds
-- a start the matchup lines leave out is not carried: that is what the games-started
-- limit looks like to the daily lines (#152, spec 0147 C17). A side with no lines carries
-- nothing. The stat's component is found by the single-component bridge, so a stat no
-- scored category is built from (a hold where holds are not scored) is judged the same.
--
-- problem is, in this order:
--   unregistered        the key has no register row and is not carried. Otherwise this is
--                       the rule on the key and not on the sum: differences that cancel,
--                       one player credited a hit ESPN does not have and another the
--                       reverse, are carried when ESPN's lines agree with them, and are
--                       still differences when they do not.
--   wrong_size          the sum differs from the registered difference by more than 1e-9.
--   null                the register accounts for the key, or the matchup lines carry it.
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

),

rules as (

    select * from {{ ref('int_fantasy__stat_components') }}
    where platform = 'espn'

),

single_component_stats as (

    -- The bridge from a stat to the credited component that is exactly it.
    {{ fo_single_component_stats('rules') }}

),

our_values as (

    -- Our side value of the key's component, picked by name from the side's totals.
    select
        keys.league_id,
        keys.season,
        keys.matchup_id,
        keys.fantasy_team_id,
        keys.stat_id,
        case bridge.component
            {%- for column in fo_batting_columns() + fo_pitching_columns() %}
            when '{{ column }}' then totals.{{ column }}
            {%- endfor %}
        end as our_value
    from keys
    inner join single_component_stats as bridge
        on bridge.stat_key = keys.stat_id
    inner join {{ ref('int_fantasy__matchup_side_totals') }} as totals
        on totals.platform = 'espn'
        and totals.league_id = keys.league_id
        and totals.season = keys.season
        and totals.matchup_id = keys.matchup_id
        and totals.fantasy_team_id = keys.fantasy_team_id

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
        when
            register.expected_difference is null
            and not coalesce(
                abs(our_values.our_value - keys.difference_sum - line_totals.matchup_line_value)
                <= 1e-9,
                false
            ) then 'unregistered'
        when abs(keys.difference_sum - register.expected_difference) > 1e-9 then 'wrong_size'
    end as problem
from keys
left join register
    on register.league_id = keys.league_id
    and register.season = keys.season
    and register.matchup_id = keys.matchup_id
    and register.team_id = keys.fantasy_team_id
    and register.stat_id = keys.stat_id
left join our_values
    on our_values.league_id = keys.league_id
    and our_values.season = keys.season
    and our_values.matchup_id = keys.matchup_id
    and our_values.fantasy_team_id = keys.fantasy_team_id
    and our_values.stat_id = keys.stat_id
left join {{ ref('rec_espn__matchup_line_totals') }} as line_totals
    on line_totals.league_id = keys.league_id
    and line_totals.season = keys.season
    and line_totals.matchup_id = keys.matchup_id
    and line_totals.fantasy_team_id = keys.fantasy_team_id
    and line_totals.stat_key = keys.stat_id
