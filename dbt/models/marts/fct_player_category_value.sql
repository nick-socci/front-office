-- What each (player, fantasy team) did in each scored category while started, and what
-- that was worth against a free-agent replacement (#11). A fct_ model records
-- measurements at a grain; this one is LONG, one row per (player, team, category), so
-- nothing here knows how many categories the league scores (ADR 0007). Day counts live
-- one table over, in fct_player_season_value, because repeating them on 17 rows would make
-- every sum 17 times the truth.
--
-- Pair: (platform_player_id, fantasy_team_id) with at least one row in
-- int_fantasy__started_player_days. Everything is summed over ALL the pair's started days,
-- inside matchups or not (ADR 0006), with whatever input_status. Production is already
-- credited by slot role upstream and is consumed as it stands.
--
-- Per category the formula comes from int_fantasy__stat_components and the list from
-- int_fantasy__categories: numerator and denominator are weighted sums of component
-- totals, exactly as int_fantasy__matchup_stat_values does for a team. A category's SIDE
-- is that of its components (batting or pitching, from the fo_*_columns lists); a test
-- fails if a category mixes sides.
--
-- played_days counts days on the category's side only: a hitter-slot day with games_batted
-- > 0 for a batting category, a pitcher-slot day with games_pitched > 0 for a pitching one.
-- The grain model's `played` means any appearance and is not used: a pitcher-slot day on
-- which a two-way player only batted must charge no pitching replacement (R4.7).
--
-- Replacement level comes from int_fantasy__replacement_levels, per played day: group
-- `hitter` for batting components; for pitching components the player's
-- dim_players.pitcher_slot_replacement_group (SP or RP). replacement_group on the row is
-- the group used for the category's side. The arithmetic (contribution, value over
-- replacement, standardised value) is in the fo_category_value macros, shared with
-- fct_transaction_impact so the two facts cannot drift; see there for the rules and for
-- what null means.
--
-- sd is the population standard deviation (stddev_pop) of value_over_replacement for a
-- category across pairs with played_days > 0 on its side. total_value one table over is
-- the sum of the standardised values.

{{ config(materialized='table') }}

{%- set batting_columns = fo_batting_columns() %}
{%- set pitching_columns = fo_pitching_columns() %}
{%- set pair_keys = ['platform', 'league_id', 'season', 'platform_player_id', 'fantasy_team_id'] %}

with pair_days as (

    select
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        count(*) filter (where slot_role = 'hitter' and games_batted > 0) as hitter_played_days,
        count(*) filter (where slot_role = 'pitcher' and games_pitched > 0) as pitcher_played_days,
        {%- for column in batting_columns + pitching_columns %}
        coalesce(sum({{ column }}), 0) as {{ column }}{{ ',' if not loop.last }}
        {%- endfor %}
    from {{ ref('int_fantasy__started_player_days') }}
    group by
        {%- for key in pair_keys %}
        {{ key }}{{ ',' if not loop.last }}
        {%- endfor %}

),

-- Which side of a player's day each component belongs to.
component_sides as (

    {%- for column in batting_columns %}
    select '{{ column }}' as component, 'batting' as side
    union all
    {%- endfor %}
    {%- for column in pitching_columns %}
    select '{{ column }}' as component, 'pitching' as side
        {{- '\n    union all' if not loop.last }}
    {%- endfor %}

),

-- One row per (pair, component): the component's total over the pair's started days.
-- One query per component rather than a pivot, as int_fantasy__matchup_stat_values does.
pair_component_totals as (

    {%- for column in batting_columns + pitching_columns %}
    select
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        '{{ column }}' as component,
        cast({{ column }} as double) as component_total
    from pair_days
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

-- The weighted sums per (pair, stat, part): what the pair did, and what a replacement
-- would have done per played day. A null level anywhere makes the replacement null; a
-- plain sum would skip it and report a partial level as complete.
category_parts as (

    select
        {%- for key in pair_keys %}
        totals.{{ key }},
        {%- endfor %}
        rules.stat_key as category_key,
        rules.part,
        max(case sides.side when 'batting' then 'hitter' else players.pitcher_slot_replacement_group end)
            as replacement_group,
        sum(rules.weight * totals.component_total) as part_total,
        case
            when bool_or(levels.level_per_played_day is null) then null
            else sum(rules.weight * levels.level_per_played_day)
        end as part_replacement
    from pair_component_totals as totals
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.platform = totals.platform
        and rules.component = totals.component
    inner join component_sides as sides
        on sides.component = totals.component
    left join {{ ref('dim_players') }} as players
        on players.platform = totals.platform
        and players.platform_player_id = totals.platform_player_id
    left join {{ ref('int_fantasy__replacement_levels') }} as levels
        on levels.component = totals.component
        and levels.replacement_group = case sides.side
            when 'batting' then 'hitter'
            else players.pitcher_slot_replacement_group
        end
    group by
        {%- for key in pair_keys %}
        totals.{{ key }},
        {%- endfor %}
        rules.stat_key,
        rules.part

),

category_sides as (

    select
        rules.platform,
        rules.stat_key as category_key,
        max(sides.side) as side
    from {{ ref('int_fantasy__stat_components') }} as rules
    inner join component_sides as sides
        on sides.component = rules.component
    group by rules.platform, rules.stat_key

),

category_parts_pivoted as (

    select
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        category_key,
        max(replacement_group) as replacement_group,
        max(part_total) filter (where part = 'numerator') as numerator,
        max(part_total) filter (where part = 'denominator') as denominator,
        max(part_replacement) filter (where part = 'numerator') as replacement_numerator,
        max(part_replacement) filter (where part = 'denominator') as replacement_denominator
    from category_parts
    group by
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        category_key

),

valued as (

    select
        {%- for key in pair_keys %}
        parts.{{ key }},
        {%- endfor %}
        parts.category_key,
        categories.category_label,
        categories.is_lower_better,
        parts.replacement_group,
        case category_sides.side
            when 'batting' then pair_days.hitter_played_days
            else pair_days.pitcher_played_days
        end as played_days,
        parts.numerator,
        parts.denominator,
        parts.replacement_numerator,
        parts.replacement_denominator
    from category_parts_pivoted as parts
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = parts.platform
        and categories.league_id = parts.league_id
        and categories.season = parts.season
        and categories.category_key = parts.category_key
    inner join category_sides
        on category_sides.platform = parts.platform
        and category_sides.category_key = parts.category_key
    inner join pair_days
        on pair_days.platform = parts.platform
        and pair_days.league_id = parts.league_id
        and pair_days.season = parts.season
        and pair_days.platform_player_id = parts.platform_player_id
        and pair_days.fantasy_team_id = parts.fantasy_team_id

),

with_value as (

    select
        *,
        {{ fo_contribution('numerator', 'denominator') }} as contribution,
        {{ fo_value_over_replacement(
            'numerator', 'denominator', 'played_days',
            'replacement_numerator', 'replacement_denominator', 'is_lower_better'
        ) }} as value_over_replacement
    from valued

),

category_spread as (

    select
        platform,
        league_id,
        season,
        category_key,
        stddev_pop(value_over_replacement) as standard_deviation
    from with_value
    where played_days > 0
    group by platform, league_id, season, category_key

)

select
    with_value.platform,
    with_value.league_id,
    with_value.season,
    with_value.platform_player_id,
    with_value.fantasy_team_id,
    with_value.category_key,
    with_value.category_label,
    with_value.is_lower_better,
    with_value.replacement_group,
    with_value.played_days,
    with_value.numerator,
    with_value.denominator,
    with_value.contribution,
    with_value.value_over_replacement,
    {{ fo_standardised_value(
        'with_value.value_over_replacement', 'with_value.played_days', 'category_spread.standard_deviation'
    ) }} as standardised_value
from with_value
left join category_spread
    on category_spread.platform = with_value.platform
    and category_spread.league_id = with_value.league_id
    and category_spread.season = with_value.season
    and category_spread.category_key = with_value.category_key
