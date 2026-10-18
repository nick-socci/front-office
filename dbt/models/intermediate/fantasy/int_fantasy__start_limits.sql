-- One row per matchup period of every covered league-season: how many starts a team's
-- slots may credit in it.
--
-- ESPN files the games-started limit as a per-day rate (stat 33, 1.857 in the 2022 to 2026
-- seasons) and applies it to the matchup period: the limit is the rate times the period's
-- own days, so 13 in a 7-day week and 22.28... in a 12-day one (ADR 0071). Periods are not
-- a uniform length here (int_fantasy__matchup_periods), which is why the days are counted
-- per period and never assumed to be a week.
--
-- start_limit is exact: a float, not rounded, null when the league-season has no stat-33
-- entry (a null limit credits every start; a zero would credit none). How ESPN rounds a
-- limit that is not a whole number is an open question in spec 0152: no period in eight
-- seasons tests it, so the comparison downstream is made against this exact value.
--
-- Only the stat-33 entry is read. A limit on another stat, or any limit in a league-season
-- that is not head-to-head, is not understood here and fails the build instead, in
-- int_fantasy__start_limits_are_understood, rather than being applied as if it were games
-- started. Only for league-seasons with rosters (ADR 0026), as
-- int_fantasy__matchup_side_totals: a limit means nothing where nothing is credited.
--
-- In the BigQuery slice, so written once for both warehouses (ADR 0051).

-- A table, as int_fantasy__matchup_periods: a contract's not_null constraints are dropped
-- on a view.
{{ config(materialized='table') }}

with period_days as (

    select
        periods.platform,
        periods.league_id,
        periods.season,
        periods.matchup_period,
        count(distinct periods.scoring_date) as period_days
    from {{ ref('int_fantasy__matchup_periods') }} as periods
    inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
        on league_seasons.platform = periods.platform
        and league_seasons.league_id = periods.league_id
        and league_seasons.season = periods.season
        and league_seasons.has_rosters
    group by periods.platform, periods.league_id, periods.season, periods.matchup_period

)

select
    period_days.platform,
    period_days.league_id,
    period_days.season,
    period_days.matchup_period,
    period_days.period_days,
    limits.limit_value as starts_per_day,
    limits.limit_value * period_days.period_days as start_limit
from period_days
left join {{ ref('stg_espn__lineup_slot_stat_limits') }} as limits
    on period_days.platform = 'espn'
    and limits.league_id = period_days.league_id
    and limits.season = period_days.season
    and limits.stat_id = 33
