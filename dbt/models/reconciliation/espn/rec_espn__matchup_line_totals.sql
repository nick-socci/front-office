-- ESPN's own matchup lines, summed per side and count stat: one row per (matchup side,
-- count stat) for every side that has lines (spec 0147, R2.2, R2.3).
--
-- The sum of the players' lines is what ESPN credited the side with after its own rules.
-- rec_espn__matchup_stat_differences sets it against our value and ESPN's total (ADR 0074),
-- and rec_espn__player_day_residuals against the side's player-day differences (ADR 0077).
-- Both read this one definition, so they cannot come to mean different things.
--
-- Counts only: the stats of int_fantasy__stat_components with no denominator part. ESPN's
-- lines carry players' rates too (WHIP, K/9), and a sum of rates is not a side's rate. A
-- composite count (SVHD, saves plus holds) is a count: ESPN's lines hold it as a stat.
--
-- A side with lines takes a stat absent from them as 0: ESPN writes no key for a stat a
-- player did not accumulate, and 316 side-stats in 2018 and 61 in later seasons are
-- absent on both ends (spec 0147, C5). A side with no lines has no row here, so no
-- consumer can read "no evidence" as zero. The cross join gives each side a row for every
-- count stat; consumers join on the stat they compare.
--
-- The sum is in a fixed order, the player id, as every floating-point sum here is.
--
-- Ephemeral: dbt inlines it as a CTE in each model that refs it, so it adds no relation
-- to the BigQuery comparison. In CI there are no matchup-days captures, so it is empty
-- there; its logic is covered by a unit test.

{{ config(materialized='ephemeral') }}

with count_stats as (

    select distinct stat_key
    from {{ ref('int_fantasy__stat_components') }}
    where
        platform = 'espn'
        and stat_key not in (
            select denominators.stat_key
            from {{ ref('int_fantasy__stat_components') }} as denominators
            where denominators.platform = 'espn' and denominators.part = 'denominator'
        )

),

sides_with_lines as (

    select distinct
        league_id,
        season,
        matchup_id,
        team_id
    from {{ ref('stg_espn__matchup_player_lines') }}

),

line_sums as (

    select
        league_id,
        season,
        matchup_id,
        team_id,
        stat_id,
        {{ fo_sum_in_order('stat_value', 'espn_player_id') }} as stat_total
    from {{ ref('stg_espn__matchup_player_lines') }}
    group by league_id, season, matchup_id, team_id, stat_id

)

select
    sides_with_lines.league_id,
    sides_with_lines.season,
    sides_with_lines.matchup_id,
    sides_with_lines.team_id as fantasy_team_id,
    count_stats.stat_key,
    coalesce(line_sums.stat_total, 0) as matchup_line_value
from sides_with_lines
cross join count_stats
left join line_sums
    on line_sums.league_id = sides_with_lines.league_id
    and line_sums.season = sides_with_lines.season
    and line_sums.matchup_id = sides_with_lines.matchup_id
    and line_sums.team_id = sides_with_lines.team_id
    and line_sums.stat_id = count_stats.stat_key
