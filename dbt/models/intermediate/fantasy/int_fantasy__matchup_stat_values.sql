-- One row per (matchup side, stat): the stat's value, computed from the side's credited
-- components by the rules in int_fantasy__stat_components.
--
-- Two steps. First the side totals are unpivoted to one row per component, by a loop
-- over the same column lists the totals were built from -- no database introspection,
-- so it compiles the same everywhere. Then each stat's numerator and denominator are
-- the weighted sums of their components, and the value is their ratio, or just the
-- numerator for a stat without a denominator.
--
-- A zero denominator gives a null value: a side with no outs has no ERA, and zero would
-- be a perfect one. 2026 never has a zero-out or zero-at-bat side, so how ESPN scores
-- one is unobserved. The null surfaces in the marts' not_null tests rather than being
-- guessed at here.

{{ config(materialized='table') }}

{%- set stat_columns = fo_batting_columns() + fo_pitching_columns() %}
{%- set side_columns = [
    'platform', 'league_id', 'season', 'matchup_id', 'matchup_period',
    'fantasy_team_id', 'opponent_team_id', 'is_home',
] %}

with components as (

    {%- for column in stat_columns %}
    select
        {{ side_columns | join(', ') }},
        '{{ column }}' as component,
        cast({{ column }} as {{ fo_type_float() }}) as component_value
    from {{ ref('int_fantasy__matchup_side_totals') }}
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

parts as (

    select
        {%- for column in side_columns %}
        components.{{ column }},
        {%- endfor %}
        rules.stat_key,
        rules.part,
        sum(rules.weight * components.component_value) as part_value
    from components
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.platform = components.platform
        and rules.component = components.component
    group by
        {%- for column in side_columns %}
        components.{{ column }},
        {%- endfor %}
        rules.stat_key,
        rules.part

)

select
    {{ side_columns | join(',\n    ') }},
    stat_key,
    max(case when part = 'numerator' then part_value end) as numerator,
    max(case when part = 'denominator' then part_value end) as denominator,
    case
        when count(case when part = 'denominator' then 1 end) = 0
            then max(case when part = 'numerator' then part_value end)
        else
            max(case when part = 'numerator' then part_value end)
            / nullif(max(case when part = 'denominator' then part_value end), 0)
    end as stat_value
from parts
group by
    {{ side_columns | join(',\n    ') }},
    stat_key
