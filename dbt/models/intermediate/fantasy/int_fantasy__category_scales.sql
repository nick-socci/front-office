-- One row per scored category: the usual gap between two teams in that category, and the
-- typical size of a side's denominator. Both value facts divide by these, so they are held
-- here once.
--
-- Why a matchup margin (ADR 0010): a category is won by finishing ahead of the other team,
-- so a unit of production matters in proportion to the usual gap between two teams. A
-- margin of innings is wide and a margin of steals is narrow; dividing each category by
-- its own margin puts them in one unit, "matchup margins".
--
-- margin_scale is a root mean square about zero, not a standard deviation about the mean.
-- Which side of a matchup is "home" is arbitrary, and a deviation about the mean would
-- change if the two sides were swapped; sqrt(avg(margin^2)) does not. Each matchup
-- contributes one margin, home minus away, and only if both sides have a value: a side
-- with a zero denominator has an undefined rate (null), and zero would be a perfect one.
--
-- side_denominator is the mean denominator of the sides that have a value, so the same
-- undefined sides are in neither the margins nor this mean. It converts a rate's value
-- over replacement (in numerator units over a player's own denominator) into the units of
-- a side. A count category has no denominator part, so its rows carry a null denominator
-- and its side_denominator is null; "is a rate" is read from the data, not listed here.
--
-- The spine is the category list, left-joined, so a scored category with no measurable
-- matchup keeps a row (matchups_measured 0, margin_scale null) rather than vanishing from
-- the facts through an inner join.
--
-- SAMPLE AND SENSITIVITY. (written in task 3)

{{ config(materialized='table') }}

with scored_values as (

    select
        values_.platform,
        values_.league_id,
        values_.season,
        values_.matchup_id,
        values_.is_home,
        categories.category_key,
        values_.denominator,
        values_.stat_value
    from {{ ref('int_fantasy__matchup_stat_values') }} as values_
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = values_.platform
        and categories.league_id = values_.league_id
        and categories.season = values_.season
        and categories.category_key = values_.stat_key

),

matchup_margins as (

    select
        home.platform,
        home.league_id,
        home.season,
        home.category_key,
        home.stat_value - away.stat_value as margin
    from scored_values as home
    inner join scored_values as away
        on away.platform = home.platform
        and away.league_id = home.league_id
        and away.season = home.season
        and away.matchup_id = home.matchup_id
        and away.category_key = home.category_key
    where home.is_home
        and not away.is_home
        and home.stat_value is not null
        and away.stat_value is not null

),

margin_scales as (

    select
        platform,
        league_id,
        season,
        category_key,
        count(*) as matchups_measured,
        sqrt(avg(margin * margin)) as margin_scale
    from matchup_margins
    group by platform, league_id, season, category_key

),

side_denominators as (

    select
        platform,
        league_id,
        season,
        category_key,
        avg(denominator) as side_denominator
    from scored_values
    where stat_value is not null
    group by platform, league_id, season, category_key

)

select
    categories.platform,
    categories.league_id,
    categories.season,
    categories.category_key,
    coalesce(margin_scales.matchups_measured, 0) as matchups_measured,
    margin_scales.margin_scale,
    side_denominators.side_denominator
from {{ ref('int_fantasy__categories') }} as categories
left join margin_scales
    on margin_scales.platform = categories.platform
    and margin_scales.league_id = categories.league_id
    and margin_scales.season = categories.season
    and margin_scales.category_key = categories.category_key
left join side_denominators
    on side_denominators.platform = categories.platform
    and side_denominators.league_id = categories.league_id
    and side_denominators.season = categories.season
    and side_denominators.category_key = categories.category_key
