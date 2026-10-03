-- The replacement pool, valued by the same macros as a player, must be worth zero in every
-- category on its group's side. Returns each (group, category) whose value over
-- replacement is not zero within 1e-9.
--
-- Each group's own pool rows of int_fantasy__replacement_levels stand in for a player:
-- numerator and denominator are the weighted pool totals, played days are the pool's, and
-- the levels are the pool's own per-played-day levels. By construction that player does
-- exactly what replacement does, so any non-zero value is a formula that has drifted from
-- the definition, or per-player rates being averaged rather than components pooled (R3.2).
-- A group with an empty pool has null levels, a null value, and is not a failure here;
-- int_fantasy__replacement_pool_has_played_days warns about it.

with component_sides as (

    {%- for column in fo_batting_columns() %}
    select '{{ column }}' as component, 'batting' as side
    union all
    {%- endfor %}
    {%- for column in fo_pitching_columns() %}
    select '{{ column }}' as component, 'pitching' as side
        {{- '\n    union all' if not loop.last }}
    {%- endfor %}

),

pool_parts as (

    select
        levels.replacement_group,
        rules.stat_key as category_key,
        rules.part,
        max(levels.pool_played_days) as pool_played_days,
        sum(rules.weight * levels.pool_total) as part_total,
        case
            when bool_or(levels.level_per_played_day is null) then null
            else sum(rules.weight * levels.level_per_played_day)
        end as part_replacement
    from {{ ref('int_fantasy__replacement_levels') }} as levels
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.component = levels.component
    inner join component_sides
        on component_sides.component = levels.component
        and component_sides.side = case levels.replacement_group when 'hitter' then 'batting' else 'pitching' end
    group by levels.replacement_group, rules.stat_key, rules.part

),

pool_categories as (

    select
        replacement_group,
        category_key,
        max(pool_played_days) as played_days,
        max(part_total) filter (where part = 'numerator') as numerator,
        max(part_total) filter (where part = 'denominator') as denominator,
        max(part_replacement) filter (where part = 'numerator') as replacement_numerator,
        max(part_replacement) filter (where part = 'denominator') as replacement_denominator
    from pool_parts
    group by replacement_group, category_key

),

valued as (

    select
        pool_categories.replacement_group,
        pool_categories.category_key,
        {{ fo_value_over_replacement(
            'pool_categories.numerator', 'pool_categories.denominator', 'pool_categories.played_days',
            'pool_categories.replacement_numerator', 'pool_categories.replacement_denominator',
            'categories.is_lower_better'
        ) }} as value_over_replacement
    from pool_categories
    inner join (
        select distinct category_key, is_lower_better
        from {{ ref('int_fantasy__categories') }}
    ) as categories
        on categories.category_key = pool_categories.category_key

)

select replacement_group, category_key, value_over_replacement
from valued
where abs(value_over_replacement) > 1e-9
