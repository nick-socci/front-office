-- A scored category's components must all be on one side of a player's day: batting or
-- pitching. Returns each category that has both.
--
-- fct_player_category_value counts played days per side and picks the replacement group
-- from the side; a category mixing the two would have no single answer for either.
-- The sides come from the same fo_batting_columns / fo_pitching_columns lists the grain
-- model is built from.

with component_sides as (

    {%- for column in fo_batting_columns() %}
    select '{{ column }}' as component, 'batting' as side
    union all
    {%- endfor %}
    {%- for column in fo_pitching_columns() %}
    select '{{ column }}' as component, 'pitching' as side
        {{- '\n    union all' if not loop.last }}
    {%- endfor %}

)

select
    rules.platform,
    rules.stat_key
from {{ ref('int_fantasy__stat_components') }} as rules
inner join {{ ref('int_fantasy__categories') }} as categories
    on categories.platform = rules.platform
    and categories.category_key = rules.stat_key
left join component_sides
    on component_sides.component = rules.component
group by rules.platform, rules.stat_key
having count(distinct component_sides.side) > 1
    or count(*) filter (where component_sides.side is null) > 0
