-- One row per scored category, in platform-neutral terms.
--
-- A categories league is defined by this list. It is read as data rather than
-- hardcoded because this league scores 17 categories, not a standard 5x5, and the
-- marts have to work for either.
--
-- is_lower_better is the renamed is_reverse: ERA and WHIP are won by the smaller
-- number, and a mart that ranks teams must not assume bigger wins. The name change is
-- deliberate -- "reverse" is ESPN's word for it and means nothing outside ESPN.
--
-- category_key stays the platform's own id, because that is what joins back to the
-- platform's own numbers when reconciling.
--
-- is_bound_by_minimum says whether the league's pitching minimum (ADR 0083) decides the
-- category. A side that pitches less than the minimum loses the categories that reward
-- pitching little: the rates, and the lower-is-better counts such as L. Counts such as K,
-- W or CG are decided by value, so the minimum does not bind them. A category is bound when
-- every component it is computed from is a pitching column, and it has a denominator or is
-- lower better. It is read from int_fantasy__stat_components, so it names no stat id; a
-- batting lower-is-better category (B_SO) is not bound, and a category with no component
-- rule is not bound.

-- Materialized as a table despite being tiny. A contract's not_null constraints are
-- silently dropped on a view -- dbt warns "Constraint types are not supported for view
-- materializations" and builds it anyway -- so a view here would enforce column names
-- and types while quietly abandoning the rest. Twelve rows is not worth a half-kept
-- promise.
{{ config(materialized='table') }}

with component_shapes as (

    select
        platform,
        stat_key,
        count(*) as component_count,
        count(case when component in (
            {%- for column in fo_pitching_columns() %}
            '{{ column }}'{{ ',' if not loop.last }}
            {%- endfor %}
        ) then 1 end) as pitching_component_count,
        count(case when part = 'denominator' then 1 end) as denominator_count
    from {{ ref('int_fantasy__stat_components') }}
    group by platform, stat_key

)

select
    'espn' as platform,
    categories.league_id,
    categories.season,
    categories.stat_id as category_key,
    categories.display_label as category_label,
    categories.stat_abbrev as category_unit,
    categories.is_reverse as is_lower_better,
    coalesce(
        shapes.pitching_component_count = shapes.component_count
        and (shapes.denominator_count > 0 or categories.is_reverse),
        false
    ) as is_bound_by_minimum
from {{ ref('stg_espn__scoring_categories') }} as categories
left join component_shapes as shapes
    on shapes.platform = 'espn'
    and shapes.stat_key = categories.stat_id
