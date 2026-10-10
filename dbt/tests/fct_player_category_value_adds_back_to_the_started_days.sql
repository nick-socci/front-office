-- The category fact itself must add back up, not only the day grain: for each fantasy team
-- and category, the numerators (and denominators) summed over the team's players in
-- fct_player_category_value must equal the same weighted component sum computed directly
-- from int_fantasy__started_player_days. Exact. Returns each (team, category, part) that
-- differs.
--
-- Catches a player-team pair lost or doubled between the grain and the fact, a component
-- weighted wrongly, and a join fan-out in the fact. It runs over every started day, inside
-- matchups or not, as the fact does (ADR 0006).

{%- set stat_columns = fo_batting_columns() + fo_pitching_columns() %}

with team_components as (

    {%- for column in stat_columns %}
    select
        platform,
        league_id,
        season,
        fantasy_team_id,
        '{{ column }}' as component,
        cast(sum({{ column }}) as double) as component_total
    from {{ ref('int_fantasy__started_player_days') }}
    group by platform, league_id, season, fantasy_team_id
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

direct as (

    select
        team_components.platform,
        team_components.league_id,
        team_components.season,
        team_components.fantasy_team_id,
        rules.stat_key as category_key,
        rules.part,
        sum(rules.weight * team_components.component_total) as direct_total
    from team_components
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.platform = team_components.platform
        and rules.component = team_components.component
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = rules.platform
        and categories.league_id = team_components.league_id
        and categories.season = team_components.season
        and categories.category_key = rules.stat_key
    group by
        team_components.platform, team_components.league_id, team_components.season,
        team_components.fantasy_team_id, rules.stat_key, rules.part

),

from_fact as (

    select
        platform,
        league_id,
        season,
        fantasy_team_id,
        category_key,
        'numerator' as part,
        sum(numerator) as fact_total
    from {{ ref('fct_player_category_value') }}
    group by platform, league_id, season, fantasy_team_id, category_key

    union all

    select
        platform,
        league_id,
        season,
        fantasy_team_id,
        category_key,
        'denominator' as part,
        sum(denominator) as fact_total
    from {{ ref('fct_player_category_value') }}
    group by platform, league_id, season, fantasy_team_id, category_key
    having count(denominator) > 0

)

select
    coalesce(direct.fantasy_team_id, from_fact.fantasy_team_id) as fantasy_team_id,
    coalesce(direct.category_key, from_fact.category_key) as category_key,
    coalesce(direct.part, from_fact.part) as part,
    direct.direct_total,
    from_fact.fact_total
from direct
full outer join from_fact
    on from_fact.platform = direct.platform
    and from_fact.league_id = direct.league_id
    and from_fact.season = direct.season
    and from_fact.fantasy_team_id = direct.fantasy_team_id
    and from_fact.category_key = direct.category_key
    and from_fact.part = direct.part
where
    direct.direct_total is null
    or from_fact.fact_total is null
    or direct.direct_total <> from_fact.fact_total
