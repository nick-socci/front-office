-- One row per (decided matchup, scored category): the margin the league host reported,
-- home minus away, and what is needed to measure a category's scale from it.
--
-- For every league-season loaded, with or without rosters. These are the host's own
-- totals, not ours: a past season is loaded for exactly these (spec 0085), and
-- int_fantasy__category_scales measures a scale from the league's earlier seasons and
-- its own decided matchups together (ADR 0027). One source for everything it blends.
--
-- WHICH MATCHUPS. Decided ones with two sides. A matchup still in progress has totals
-- that are moving, and a bye has one side; ESPN reports both as UNDECIDED. A side with no
-- reported total for a scored category leaves that row out.
--
-- is_measured says whether a row counts toward a scale. Rows that do not are kept, so
-- that what was left out can be seen:
--   * a playoff matchup, of any tier, is not measured. A consolation matchup is not a
--     contest both sides are trying to win, and a value is in units of a week that is
--     (owner, 2026-10-08). The winners' bracket goes with it: one rule, not two.
--   * a rate is measured only when both sides' denominators are reported and above zero.
--     A rate on a zero denominator is undefined, as int_fantasy__matchup_stat_values has
--     it for our own totals; ESPN reports it as 0.00, which read at face value is the
--     best ERA there can be. And a rate's scale and its denominator have to come from the
--     same matchups, so a matchup with no reported denominator measures neither.
--   * a matchup period in which nothing was played (relative_volume 0) is not measured.
--
-- RATES AND THEIR DENOMINATORS are read from the rules, never listed here. A category is
-- a rate if int_fantasy__stat_components gives it a denominator part; a side's
-- denominator is the weighted sum of the host's reported totals for those components,
-- each found through fo_single_component_stats, and null if any is not reported. A
-- category with no rule at all is carried as a count. ESPN reports at-bats from 2019 on
-- and not in 2018.
--
-- RELATIVE VOLUME. Matchup periods are not one length: the opening period and the
-- All-Star break hold about one and a half usual weeks, and a count's margins are 38%
-- wider in them. Days are known for few seasons and mislead where they are known (2025's
-- 13-day opening period holds 0.65 of a week's play), so length is measured by what was
-- played. For a period: over the counting categories the league-season scores, the
-- median of (the period's mean reported side total / the median of that mean over the
-- league-season's regular-season periods). A median over categories so that one
-- low-count category's odd week does not move it; a category whose usual total is zero
-- is left out. With no counting category to measure from, the relative volume is 1:
-- length cannot be measured, so nothing is adjusted (spec 0057, amendment). The usual
-- period is the median of those decided so far, so a league-season's first period has a
-- relative volume of 1 until others are decided.
--
-- STANDARD MARGIN. The margin restated for a period of usual volume. A count summed over
-- more play has gaps that grow with the square root of how much; a rate's shrink by the
-- same factor. The square root is how sums of independent days behave and is not fitted:
-- measured, the long periods stay about 12% wide after it.

{{ config(materialized='table') }}

with rules as (

    select * from {{ ref('int_fantasy__stat_components') }}
    where platform = 'espn'

),

bridge as (

    {{ fo_single_component_stats('rules') }}

),

denominator_parts as (

    -- One row per (rate category, denominator component), with the host stat that is
    -- exactly that component, or null if the host has none.
    select
        rules.stat_key as category_key,
        rules.weight,
        bridge.stat_key as reported_stat_key
    from rules
    left join bridge
        on bridge.component = rules.component
    where rules.part = 'denominator'

),

rate_categories as (

    select distinct category_key from denominator_parts

),

decided_matchups as (

    select
        league_id,
        season,
        matchup_id,
        matchup_period,
        playoff_tier = 'NONE' as is_regular_season
    from {{ ref('stg_espn__matchups') }}
    where
        winner != 'UNDECIDED'
        and home_team_id is not null
        and away_team_id is not null

),

reported as (

    select
        league_id,
        season,
        matchup_id,
        side,
        stat_id,
        score
    from {{ ref('stg_espn__matchup_category_results') }}

),

side_totals as (

    -- One row per (decided matchup, side, scored category), reported or not.
    select
        categories.platform,
        matchups.league_id,
        matchups.season,
        matchups.matchup_id,
        matchups.matchup_period,
        matchups.is_regular_season,
        sides.side,
        categories.category_key,
        rate_categories.category_key is not null as is_rate,
        reported.score
    from decided_matchups as matchups
    cross join (
        select 'home' as side
        union all
        select 'away' as side
    ) as sides
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = 'espn'
        and categories.league_id = matchups.league_id
        and categories.season = matchups.season
    left join rate_categories
        on rate_categories.category_key = categories.category_key
    left join reported
        on reported.league_id = matchups.league_id
        and reported.season = matchups.season
        and reported.matchup_id = matchups.matchup_id
        and reported.side = sides.side
        and reported.stat_id = categories.category_key

),

side_denominators as (

    -- Null unless every denominator component has a reported total on this side.
    select
        side_totals.league_id,
        side_totals.season,
        side_totals.matchup_id,
        side_totals.side,
        side_totals.category_key,
        case
            when count(*) = count(reported.score) then sum(parts.weight * reported.score)
        end as denominator
    from side_totals
    inner join denominator_parts as parts
        on parts.category_key = side_totals.category_key
    left join reported
        on reported.league_id = side_totals.league_id
        and reported.season = side_totals.season
        and reported.matchup_id = side_totals.matchup_id
        and reported.side = side_totals.side
        and reported.stat_id = parts.reported_stat_key
    group by
        side_totals.league_id,
        side_totals.season,
        side_totals.matchup_id,
        side_totals.side,
        side_totals.category_key

),

period_means as (

    -- A counting category's mean reported side total in each regular-season period.
    select
        league_id,
        season,
        matchup_period,
        category_key,
        avg(score) as mean_side_total
    from side_totals
    where
        is_regular_season
        and not is_rate
        and score is not null
    group by league_id, season, matchup_period, category_key

),

usual_means as (

    select
        league_id,
        season,
        category_key,
        median(mean_side_total) as usual_side_total
    from period_means
    group by league_id, season, category_key

),

regular_periods as (

    select distinct
        league_id,
        season,
        matchup_period
    from decided_matchups
    where is_regular_season

),

period_volumes as (

    -- Spined on the periods, so a period no counting category can measure still has a
    -- row: its relative volume is 1.
    select
        periods.league_id,
        periods.season,
        periods.matchup_period,
        coalesce(
            median(period_means.mean_side_total / usual_means.usual_side_total),
            1
        ) as relative_volume
    from regular_periods as periods
    left join period_means
        on period_means.league_id = periods.league_id
        and period_means.season = periods.season
        and period_means.matchup_period = periods.matchup_period
    left join usual_means
        on usual_means.league_id = period_means.league_id
        and usual_means.season = period_means.season
        and usual_means.category_key = period_means.category_key
        and usual_means.usual_side_total > 0
    group by periods.league_id, periods.season, periods.matchup_period

),

margins as (

    select
        home.platform,
        home.league_id,
        home.season,
        home.matchup_id,
        home.category_key,
        home.is_regular_season,
        home.score - away.score as margin,
        home.is_rate,
        home_denominators.denominator as home_denominator,
        away_denominators.denominator as away_denominator,
        period_volumes.relative_volume
    from side_totals as home
    inner join side_totals as away
        on away.league_id = home.league_id
        and away.season = home.season
        and away.matchup_id = home.matchup_id
        and away.category_key = home.category_key
        and away.side = 'away'
    left join side_denominators as home_denominators
        on home_denominators.league_id = home.league_id
        and home_denominators.season = home.season
        and home_denominators.matchup_id = home.matchup_id
        and home_denominators.category_key = home.category_key
        and home_denominators.side = 'home'
    left join side_denominators as away_denominators
        on away_denominators.league_id = home.league_id
        and away_denominators.season = home.season
        and away_denominators.matchup_id = home.matchup_id
        and away_denominators.category_key = home.category_key
        and away_denominators.side = 'away'
    -- Only regular-season periods have a volume, so a playoff matchup's is null.
    left join period_volumes
        on period_volumes.league_id = home.league_id
        and period_volumes.season = home.season
        and period_volumes.matchup_period = home.matchup_period
        and home.is_regular_season
    where
        home.side = 'home'
        and home.score is not null
        and away.score is not null

)

select
    platform,
    league_id,
    season,
    matchup_id,
    category_key,
    is_regular_season,
    margin,
    is_rate,
    home_denominator,
    away_denominator,
    relative_volume,
    case
        when relative_volume is null or relative_volume <= 0 then null
        when is_rate then margin * sqrt(relative_volume)
        else margin / sqrt(relative_volume)
    end as standard_margin,
    is_regular_season
    and coalesce(relative_volume > 0, false)
    and (not is_rate or coalesce(home_denominator > 0 and away_denominator > 0, false))
        as is_measured
from margins
