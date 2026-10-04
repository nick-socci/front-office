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
-- KIND OF DAY (ADR 0008, #52). A pair's days are grouped by kind and each kind is valued
-- against its own replacement level: `batting` (a hitter-slot day with games_batted > 0),
-- `start` or `relief` (a pitcher-slot day, by fo_pitching_day_kind from that day's own
-- games_pitched and games_started). A start is compared with what a free agent produced
-- in a start, a relief day with what one produced in relief, because a played day of six
-- innings and one of a single inning are not the same unit. Nothing about the player
-- (default position, eligibility, roster slot) chooses a level; the outing does. A
-- started day that is not a played day on its slot's side belongs to no kind: its
-- credited components are all zero, since they come from the same MLB row as the games
-- counts, so it adds nothing. Batting has one kind, so a batting row is computed exactly
-- as before the kinds existed.
--
-- A pair's row for a category sums over the kinds on that category's side (batting
-- categories: batting; pitching categories: start and relief): numerator, denominator and
-- played_days are plain sums, and value_over_replacement is the sum of the per-kind
-- values. It is NULL if ANY kind the pair played has a null value (a null level, an empty
-- pool): a plain sum skips nulls and would report a partial value as complete (R2.2). A
-- pair with no played day on the side has value 0 and no null, as fo_category_value says.
--
-- THE SPINE. The rows come from every pair crossed with the scored categories, with the
-- per-kind values left-joined on. Grouping by kind alone would give a pair with no pitched
-- day (266 of 580 in 2026) no pitching group and so no pitching rows; the spine keeps all
-- of them, with 0 played days, numerator 0, a rate's denominator 0 (a count's stays null)
-- and value 0, as before.
--
-- played_days counts days on the category's side only, summed over its kinds. The grain
-- model's `played` means any appearance and is not used: a pitcher-slot day on which a
-- two-way player only batted must charge no pitching replacement (R4.7).
--
-- Replacement level comes from int_fantasy__replacement_levels, per played day of the
-- kind. The arithmetic (contribution, value over replacement, standardised value) is in
-- the fo_category_value macros, shared with fct_transaction_impact so the two facts cannot
-- drift; see there for the rules and for what null means.
--
-- sd is the population standard deviation (stddev_pop) of value_over_replacement for a
-- category across pairs with played_days > 0 on its side. total_value one table over is
-- the sum of the standardised values.

{{ config(materialized='table') }}

{%- set batting_columns = fo_batting_columns() %}
{%- set pitching_columns = fo_pitching_columns() %}
{%- set pair_keys = ['platform', 'league_id', 'season', 'platform_player_id', 'fantasy_team_id'] %}

with pairs as (

    select distinct
        {%- for key in pair_keys %}
        {{ key }}{{ ',' if not loop.last }}
        {%- endfor %}
    from {{ ref('int_fantasy__started_player_days') }}

),

-- Each played day with its kind. A started day that is not a played day on its slot's
-- side has no kind and is dropped here.
kinded_days as (

    select
        *,
        case slot_role
            when 'hitter' then case when games_batted > 0 then 'batting' end
            when 'pitcher' then {{ fo_pitching_day_kind('games_pitched', 'games_started') }}
        end as day_kind
    from {{ ref('int_fantasy__started_player_days') }}

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

kind_days as (

    select
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        day_kind,
        count(*) as played_days,
        {%- for column in batting_columns + pitching_columns %}
        coalesce(sum({{ column }}), 0) as {{ column }}{{ ',' if not loop.last }}
        {%- endfor %}
    from kinded_days
    where day_kind is not null
    group by
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        day_kind

),

-- One row per (pair, kind, component): the component's total over the pair's days of that
-- kind. One query per component rather than a pivot, as int_fantasy__matchup_stat_values
-- does.
kind_component_totals as (

    {%- for column in batting_columns + pitching_columns %}
    select
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        day_kind,
        '{{ column }}' as component,
        cast({{ column }} as double) as component_total
    from kind_days
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

-- The weighted sums per (pair, kind, stat, part): what the pair did on days of that kind,
-- and what a replacement would have done per played day of that kind. A null level
-- anywhere makes the replacement null; a plain sum would skip it and report a partial
-- level as complete.
kind_parts as (

    select
        {%- for key in pair_keys %}
        totals.{{ key }},
        {%- endfor %}
        totals.day_kind,
        rules.stat_key as category_key,
        rules.part,
        sum(rules.weight * totals.component_total) as part_total,
        case
            when bool_or(levels.level_per_played_day is null) then null
            else sum(rules.weight * levels.level_per_played_day)
        end as part_replacement
    from kind_component_totals as totals
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.platform = totals.platform
        and rules.component = totals.component
    inner join component_sides as sides
        on sides.component = totals.component
        -- a kind meets only the components of its own side
        and sides.side = case totals.day_kind when 'batting' then 'batting' else 'pitching' end
    left join {{ ref('int_fantasy__replacement_levels') }} as levels
        on levels.component = totals.component
        and levels.day_kind = totals.day_kind
    group by
        {%- for key in pair_keys %}
        totals.{{ key }},
        {%- endfor %}
        totals.day_kind,
        rules.stat_key,
        rules.part

),

-- A category's side, and whether it is a rate (has a denominator part) or a count.
category_sides as (

    select
        rules.platform,
        rules.stat_key as category_key,
        max(sides.side) as side,
        bool_or(rules.part = 'denominator') as is_rate
    from {{ ref('int_fantasy__stat_components') }} as rules
    inner join component_sides as sides
        on sides.component = rules.component
    group by rules.platform, rules.stat_key

),

kind_parts_pivoted as (

    select
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        day_kind,
        category_key,
        max(part_total) filter (where part = 'numerator') as numerator,
        max(part_total) filter (where part = 'denominator') as denominator,
        max(part_replacement) filter (where part = 'numerator') as replacement_numerator,
        max(part_replacement) filter (where part = 'denominator') as replacement_denominator
    from kind_parts
    group by
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        day_kind,
        category_key

),

-- One row per (pair, kind, category) with that kind's value over replacement.
kind_values as (

    select
        {%- for key in pair_keys %}
        parts.{{ key }},
        {%- endfor %}
        parts.category_key,
        kind_days.played_days,
        parts.numerator,
        parts.denominator,
        {{ fo_value_over_replacement(
            'parts.numerator', 'parts.denominator', 'kind_days.played_days',
            'parts.replacement_numerator', 'parts.replacement_denominator', 'categories.is_lower_better'
        ) }} as value_over_replacement
    from kind_parts_pivoted as parts
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = parts.platform
        and categories.league_id = parts.league_id
        and categories.season = parts.season
        and categories.category_key = parts.category_key
    inner join kind_days
        on kind_days.platform = parts.platform
        and kind_days.league_id = parts.league_id
        and kind_days.season = parts.season
        and kind_days.platform_player_id = parts.platform_player_id
        and kind_days.fantasy_team_id = parts.fantasy_team_id
        and kind_days.day_kind = parts.day_kind

),

-- The sum over kinds for each (pair, category) the pair has a played day in. The value is
-- null if any kind's value is null.
summed_over_kinds as (

    select
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        category_key,
        cast(sum(played_days) as bigint) as played_days,
        sum(numerator) as numerator,
        sum(denominator) as denominator,
        case
            when bool_or(value_over_replacement is null) then null
            else sum(value_over_replacement)
        end as value_over_replacement
    from kind_values
    group by
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        category_key

),

-- Every pair crossed with every scored category, with the summed values left-joined on:
-- a pair with no played day on a category's side is worth 0 there, not absent.
with_value as (

    select
        {%- for key in pair_keys %}
        pairs.{{ key }},
        {%- endfor %}
        categories.category_key,
        categories.category_label,
        categories.is_lower_better,
        coalesce(summed.played_days, 0) as played_days,
        coalesce(summed.numerator, 0) as numerator,
        case
            when category_sides.is_rate then coalesce(summed.denominator, 0)
        end as denominator,
        case
            when summed.category_key is null then 0
            else summed.value_over_replacement
        end as value_over_replacement
    from pairs
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = pairs.platform
        and categories.league_id = pairs.league_id
        and categories.season = pairs.season
    inner join category_sides
        on category_sides.platform = categories.platform
        and category_sides.category_key = categories.category_key
    left join summed_over_kinds as summed
        on summed.platform = pairs.platform
        and summed.league_id = pairs.league_id
        and summed.season = pairs.season
        and summed.platform_player_id = pairs.platform_player_id
        and summed.fantasy_team_id = pairs.fantasy_team_id
        and summed.category_key = categories.category_key

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
    with_value.played_days,
    with_value.numerator,
    with_value.denominator,
    {{ fo_contribution('with_value.numerator', 'with_value.denominator') }} as contribution,
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
