-- One row per (matchup side, stat) on either end: our recomputed value against ESPN's
-- scoreByStat, and a status saying whether any difference is accounted for.
--
-- This is the reconciliation (#10). It pairs the production marts' inputs with ESPN
-- staging, which only this boundary may do. A full outer join, so a side or stat that
-- exists on one end only is a row with a status, never silently dropped.
--
-- Only league-seasons with rosters are compared (ADR 0026). A past season loaded for its
-- matchup totals alone has ESPN's side and, by design, nothing of ours: every one of its
-- rows would be 'missing_ours', which is a finding about a season we compute, not a
-- description of one we do not. ESPN's side is restricted where it is read, so the
-- formula check and the bye rule below see the same seasons.
--
-- status, decided in this order:
--   bye                    ESPN reports the bye team's stats; a bye has no opponent or
--                          result, and is out of scope (2 sides in 2026).
--   missing_ours           ESPN has the side or stat, we don't.
--   missing_espn           we have it, ESPN doesn't.
--   unverified             the side rests on a missing boxscore or unresolved player
--                          (#25): not compared, because a difference would prove nothing.
--   formula_mismatch       a rate: our formula applied to ESPN's OWN components does
--                          not reproduce ESPN's rate. The formula is wrong, whatever our
--                          inputs say.
--   match                  within tolerance: exact for counts, 1e-6 for rates.
--   registered             a count off by exactly the difference recorded for this
--                          league-season, matchup, side and stat in the
--                          espn_reconciliation_residuals seed, with its cause.
--   explained_by_component a rate that differs from ESPN's but equals, within 1e-6, the
--                          rate the register implies: our rules applied to ESPN's own
--                          components, each shifted by its registered difference on
--                          this side. Rates are never registered themselves; their
--                          difference must follow exactly from the components'.
--   unexplained            anything else. The singular test fails on it.
-- A registered residual that no longer occurs leaves its seed row attached to no
-- 'registered' row; the test fails on that too, so the register cannot go stale.

{{ config(materialized='table') }}

with rules as (

    select * from {{ ref('int_fantasy__stat_components') }}
    where platform = 'espn'

),

rate_stats as (

    select distinct stat_key from rules
    where part = 'denominator'

),

single_component_stats as (

    -- The bridge from a component column to the ESPN stat that is exactly it.
    {{ fo_single_component_stats('rules') }}

),

covered as (

    select
        league_id,
        season
    from {{ ref('int_fantasy__league_seasons') }}
    where platform = 'espn' and has_rosters

),

espn as (

    select
        results.league_id,
        results.season,
        results.matchup_id,
        results.team_id as fantasy_team_id,
        results.stat_id as stat_key,
        results.score as espn_value
    from {{ ref('stg_espn__matchup_category_results') }} as results
    inner join covered
        on covered.league_id = results.league_id
        and covered.season = results.season

),

played_matchups as (

    select
        league_id,
        season,
        matchup_id
    from {{ ref('stg_espn__matchups') }}

),

ours as (

    select
        stat_values.league_id,
        stat_values.season,
        stat_values.matchup_id,
        stat_values.fantasy_team_id,
        stat_values.stat_key,
        stat_values.stat_value as our_value,
        totals.verified_player_days = totals.started_player_days as is_verified
    from {{ ref('int_fantasy__matchup_stat_values') }} as stat_values
    inner join {{ ref('int_fantasy__matchup_side_totals') }} as totals
        on totals.platform = stat_values.platform
        and totals.league_id = stat_values.league_id
        and totals.season = stat_values.season
        and totals.matchup_id = stat_values.matchup_id
        and totals.fantasy_team_id = stat_values.fantasy_team_id
    where stat_values.platform = 'espn'

),

register as (

    select * from {{ ref('espn_reconciliation_residuals') }}

),

-- Each rate recomputed by our rules from ESPN's own component scores, twice: as ESPN
-- reports them (which must reproduce ESPN's rate -- the formula check), and shifted by
-- this side's registered residuals (the rate the register implies -- what ours must be).
espn_formula as (

    select
        espn.league_id,
        espn.season,
        espn.matchup_id,
        espn.fantasy_team_id,
        rules.stat_key,
        sum(rules.weight * component_scores.espn_value) filter (where rules.part = 'numerator')
        / nullif(
            sum(rules.weight * component_scores.espn_value) filter (
                where rules.part = 'denominator'
            ),
            0
        ) as espn_formula_value,
        sum(
            rules.weight * (component_scores.espn_value + coalesce(register.expected_difference, 0))
        )
        filter (where rules.part = 'numerator')
        / nullif(
            sum(
                rules.weight
                * (component_scores.espn_value + coalesce(register.expected_difference, 0))
            )
            filter (where rules.part = 'denominator'),
            0
        ) as implied_value
    from espn
    inner join rules
        on rules.stat_key = espn.stat_key
    inner join rate_stats
        on rate_stats.stat_key = rules.stat_key
    inner join single_component_stats as bridge
        on bridge.component = rules.component
    inner join espn as component_scores
        on component_scores.league_id = espn.league_id
        and component_scores.season = espn.season
        and component_scores.matchup_id = espn.matchup_id
        and component_scores.fantasy_team_id = espn.fantasy_team_id
        and component_scores.stat_key = bridge.stat_key
    left join register
        on register.league_id = espn.league_id
        and register.season = espn.season
        and register.matchup_id = espn.matchup_id
        and register.team_id = espn.fantasy_team_id
        and register.stat_id = bridge.stat_key
    group by espn.league_id, espn.season, espn.matchup_id, espn.fantasy_team_id, rules.stat_key

),

compared as (

    select
        coalesce(ours.league_id, espn.league_id) as league_id,
        coalesce(ours.season, espn.season) as season,
        coalesce(ours.matchup_id, espn.matchup_id) as matchup_id,
        coalesce(ours.fantasy_team_id, espn.fantasy_team_id) as fantasy_team_id,
        coalesce(ours.stat_key, espn.stat_key) as stat_key,
        ours.our_value,
        espn.espn_value,
        ours.our_value - espn.espn_value as difference,
        ours.is_verified,
        ours.stat_key is not null as has_ours,
        espn.stat_key is not null as has_espn
    from ours
    full outer join espn
        on espn.league_id = ours.league_id
        and espn.season = ours.season
        and espn.matchup_id = ours.matchup_id
        and espn.fantasy_team_id = ours.fantasy_team_id
        and espn.stat_key = ours.stat_key

),

annotated as (

    select
        compared.*,
        rate_stats.stat_key is not null as is_rate,
        case when rate_stats.stat_key is not null then 1e-6 else 1e-9 end as tolerance,
        espn_formula.espn_formula_value,
        espn_formula.implied_value,
        played_matchups.matchup_id is null as is_bye,
        register.expected_difference as registered_difference,
        register.cause as registered_cause
    from compared
    left join rate_stats
        on rate_stats.stat_key = compared.stat_key
    left join espn_formula
        on espn_formula.league_id = compared.league_id
        and espn_formula.season = compared.season
        and espn_formula.matchup_id = compared.matchup_id
        and espn_formula.fantasy_team_id = compared.fantasy_team_id
        and espn_formula.stat_key = compared.stat_key
    left join played_matchups
        on played_matchups.league_id = compared.league_id
        and played_matchups.season = compared.season
        and played_matchups.matchup_id = compared.matchup_id
    left join register
        on register.league_id = compared.league_id
        and register.season = compared.season
        and register.matchup_id = compared.matchup_id
        and register.team_id = compared.fantasy_team_id
        and register.stat_id = compared.stat_key

)

select
    league_id,
    season,
    matchup_id,
    fantasy_team_id,
    stat_key,
    is_rate,
    our_value,
    espn_value,
    difference,
    espn_formula_value,
    implied_value,
    registered_difference,
    registered_cause,
    case
        when not has_ours and is_bye then 'bye'
        when not has_ours then 'missing_ours'
        when not has_espn then 'missing_espn'
        when not is_verified then 'unverified'
        when is_rate and (
            espn_formula_value is null
            or abs(espn_formula_value - espn_value) > tolerance
        ) then 'formula_mismatch'
        when
            our_value is not null and abs(difference) <= tolerance
            and registered_difference is null then 'match'
        when
            not is_rate and registered_difference is not null
            and abs(difference - registered_difference) <= tolerance then 'registered'
        when
            is_rate and our_value is not null and implied_value is not null
            and abs(our_value - implied_value) <= tolerance then 'explained_by_component'
        else 'unexplained'
    end as status
from annotated
