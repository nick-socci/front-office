-- What each add or drop opened up, valued on the same scale as a player's season (#11).
-- One row per transaction. An add is valued by what the player did for the adding team
-- while it started him; a drop by what he did for the rest of the season, for whoever had
-- him: the cost of letting him go. Neither is a counterfactual about the lineup, only a
-- window of production measured against a free-agent replacement.
--
-- Carries no league_id or season, like int_fantasy__transactions (#28): it assumes the one
-- league-season loaded, and #28 must land before a second is.
--
-- The window, both ends inclusive, from the first and last scoring dates of
-- int_fantasy__matchup_periods:
--   add   starts on greatest(transaction_date, first scoring date) and ends on the date of
--         THAT TEAM's next drop of THAT PLAYER, else the last scoring date. "Next" is by
--         transacted_at, not by date: the real season has same-day add-and-drops, and a
--         drop earlier the same day belongs to an earlier stint. A drop before the first
--         scoring date makes the window empty (start stays the first scoring date, end is
--         the drop's date, every count is 0);
--   drop  starts on greatest(transaction_date + 1, first scoring date) and ends on the last
--         scoring date. It does NOT stop at a re-add: the question is what the roster
--         gave up, not what the next team did with him. next_added_at and
--         next_added_by_team_id record the earliest add by any team after the drop. An
--         empty window (a drop on the last day) counts 0.
--
-- Measures. An add counts, over the window: rostered_days (roster days of that player on
-- that team), started_days, played_started_days (the credited-side appearance, as in
-- fct_player_season_value) and the credited components of int_fantasy__started_player_days.
-- A drop counts MLB days from int_mlb__player_game_days for his dim_players.mlbam_player_id,
-- on the side his replacement_group is credited for only (hitter: batting columns and
-- played_days = days with games_batted > 0; SP and RP: pitching columns and days with
-- games_pitched > 0); the other side is 0. rostered_days, started_days and
-- played_started_days are null on a drop, played_days is null on an add. A dropped player
-- with no MLBAM id or group is unresolved: zeroes, and a NULL total_value, because 0
-- would read as replacement level.
--
-- total_value is on the scale of fct_player_category_value: the same per-category
-- arithmetic (the fo_category_value macros), the same replacement levels and the same
-- standard deviation, which is READ from that fact (population sd of value_over_replacement
-- over rows with played_days > 0 per category), never recomputed over transactions, or a
-- two-week window and a season would not be comparable. Played days are those on the
-- category's side. Batting is measured against group `hitter`; pitching against the
-- player's pitcher_slot_replacement_group on an add (his slot, as the season fact does) and
-- against his replacement_group on a drop. total_value is the sum of the standardised
-- values over every scored category, NULL if any is NULL.

{{ config(materialized='table') }}

{%- set batting_columns = fo_batting_columns() %}
{%- set pitching_columns = fo_pitching_columns() %}
{%- set component_columns = batting_columns + pitching_columns %}

with scoring_bounds as (

    select
        min(scoring_date) as first_scoring_date,
        max(scoring_date) as last_scoring_date
    from {{ ref('int_fantasy__matchup_periods') }}

),

transactions as (

    select * from {{ ref('int_fantasy__transactions') }}

),

-- For each add, the date of the same team's earliest later drop of the same player.
next_team_drops as (

    select
        adds.transaction_id,
        min(drops.transaction_date) as next_drop_date
    from transactions as adds
    inner join transactions as drops
        on drops.platform = adds.platform
        and drops.platform_player_id = adds.platform_player_id
        and drops.fantasy_team_id = adds.fantasy_team_id
        and drops.movement = 'drop'
        and drops.transacted_at > adds.transacted_at
    where adds.movement = 'add'
    group by adds.transaction_id

),

windows as (

    select
        transactions.*,
        players.mlbam_player_id,
        players.replacement_group,
        players.pitcher_slot_replacement_group,
        case transactions.movement
            when 'add' then greatest(transactions.transaction_date, bounds.first_scoring_date)
            when 'drop' then greatest(transactions.transaction_date + 1, bounds.first_scoring_date)
        end as window_start,
        case transactions.movement
            when 'add' then coalesce(next_team_drops.next_drop_date, bounds.last_scoring_date)
            when 'drop' then bounds.last_scoring_date
        end as window_end
    from transactions
    cross join scoring_bounds as bounds
    left join next_team_drops
        on next_team_drops.transaction_id = transactions.transaction_id
    left join {{ ref('dim_players') }} as players
        on players.platform = transactions.platform
        and players.platform_player_id = transactions.platform_player_id

),

add_rostered as (

    select
        windows.transaction_id,
        count(*) as rostered_days
    from windows
    inner join {{ ref('int_fantasy__roster_days') }} as days
        on days.platform = windows.platform
        and days.platform_player_id = windows.platform_player_id
        and days.fantasy_team_id = windows.fantasy_team_id
        and days.scoring_date between windows.window_start and windows.window_end
    where windows.movement = 'add'
    group by windows.transaction_id

),

add_started as (

    select
        windows.transaction_id,
        count(*) as started_days,
        count(*) filter (where days.slot_role = 'hitter' and days.games_batted > 0) as hitter_played_days,
        count(*) filter (where days.slot_role = 'pitcher' and days.games_pitched > 0) as pitcher_played_days,
        {%- for column in component_columns %}
        coalesce(sum(days.{{ column }}), 0) as {{ column }}{{ ',' if not loop.last }}
        {%- endfor %}
    from windows
    inner join {{ ref('int_fantasy__started_player_days') }} as days
        on days.platform = windows.platform
        and days.platform_player_id = windows.platform_player_id
        and days.fantasy_team_id = windows.fantasy_team_id
        and days.scoring_date between windows.window_start and windows.window_end
    where windows.movement = 'add'
    group by windows.transaction_id

),

-- A drop's MLB days, only on the side his group is credited for.
drop_games as (

    select
        windows.transaction_id,
        count(*) filter (where windows.replacement_group = 'hitter' and games.games_batted > 0)
            as hitter_played_days,
        count(*) filter (where windows.replacement_group in ('SP', 'RP') and games.games_pitched > 0)
            as pitcher_played_days,
        {%- for column in batting_columns %}
        coalesce(sum(case when windows.replacement_group = 'hitter' then games.{{ column }} end), 0)
            as {{ column }},
        {%- endfor %}
        {%- for column in pitching_columns %}
        coalesce(sum(case when windows.replacement_group in ('SP', 'RP') then games.{{ column }} end), 0)
            as {{ column }}{{ ',' if not loop.last }}
        {%- endfor %}
    from windows
    inner join {{ ref('int_mlb__player_game_days') }} as games
        on games.mlbam_player_id = windows.mlbam_player_id
        and games.game_date between windows.window_start and windows.window_end
    where windows.movement = 'drop'
    group by windows.transaction_id

),

-- The earliest add of the player by any team after each drop; transaction_id breaks a tie
-- in transacted_at.
next_adds as (

    select
        transaction_id,
        next_added_at,
        next_added_by_team_id
    from (
        select
            drops.transaction_id,
            adds.transacted_at as next_added_at,
            adds.fantasy_team_id as next_added_by_team_id,
            row_number() over (
                partition by drops.transaction_id
                order by adds.transacted_at, adds.transaction_id
            ) as add_rank
        from transactions as drops
        inner join transactions as adds
            on adds.platform = drops.platform
            and adds.platform_player_id = drops.platform_player_id
            and adds.movement = 'add'
            and adds.transacted_at > drops.transacted_at
        where drops.movement = 'drop'
    )
    where add_rank = 1

),

measured as (

    select
        windows.*,
        case windows.movement when 'add' then coalesce(add_rostered.rostered_days, 0) end as rostered_days,
        case windows.movement when 'add' then coalesce(add_started.started_days, 0) end as started_days,
        case windows.movement
            when 'add' then coalesce(add_started.hitter_played_days, 0) + coalesce(add_started.pitcher_played_days, 0)
        end as played_started_days,
        case windows.movement
            when 'drop' then coalesce(drop_games.hitter_played_days, 0) + coalesce(drop_games.pitcher_played_days, 0)
        end as played_days,
        coalesce(add_started.hitter_played_days, drop_games.hitter_played_days, 0) as hitter_played_days,
        coalesce(add_started.pitcher_played_days, drop_games.pitcher_played_days, 0) as pitcher_played_days,
        case windows.movement
            when 'add' then windows.pitcher_slot_replacement_group
            else windows.replacement_group
        end as pitching_replacement_group,
        next_adds.next_added_at,
        next_adds.next_added_by_team_id,
        {%- for column in component_columns %}
        coalesce(add_started.{{ column }}, drop_games.{{ column }}, 0) as {{ column }}{{ ',' if not loop.last }}
        {%- endfor %}
    from windows
    left join add_rostered
        on add_rostered.transaction_id = windows.transaction_id
    left join add_started
        on add_started.transaction_id = windows.transaction_id
    left join drop_games
        on drop_games.transaction_id = windows.transaction_id
    left join next_adds
        on next_adds.transaction_id = windows.transaction_id

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

-- One row per (transaction, component): the component's total over the window.
transaction_component_totals as (

    {%- for column in component_columns %}
    select
        platform,
        transaction_id,
        pitching_replacement_group,
        '{{ column }}' as component,
        cast({{ column }} as double) as component_total
    from measured
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

-- The weighted sums per (transaction, stat, part): what the window held, and what a
-- replacement would have done per played day. A null level anywhere makes the replacement
-- null, as in fct_player_category_value.
category_parts as (

    select
        totals.platform,
        totals.transaction_id,
        rules.stat_key as category_key,
        rules.part,
        sum(rules.weight * totals.component_total) as part_total,
        case
            when bool_or(levels.level_per_played_day is null) then null
            else sum(rules.weight * levels.level_per_played_day)
        end as part_replacement
    from transaction_component_totals as totals
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.platform = totals.platform
        and rules.component = totals.component
    inner join component_sides as sides
        on sides.component = totals.component
    left join {{ ref('int_fantasy__replacement_levels') }} as levels
        on levels.component = totals.component
        and levels.replacement_group = case sides.side
            when 'batting' then 'hitter'
            else totals.pitching_replacement_group
        end
    group by totals.platform, totals.transaction_id, rules.stat_key, rules.part

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
        platform,
        transaction_id,
        category_key,
        max(part_total) filter (where part = 'numerator') as numerator,
        max(part_total) filter (where part = 'denominator') as denominator,
        max(part_replacement) filter (where part = 'numerator') as replacement_numerator,
        max(part_replacement) filter (where part = 'denominator') as replacement_denominator
    from category_parts
    group by platform, transaction_id, category_key

),

scored_categories as (

    select distinct
        category_key,
        is_lower_better
    from {{ ref('int_fantasy__categories') }}

),

valued as (

    select
        parts.transaction_id,
        parts.category_key,
        scored_categories.is_lower_better,
        case category_sides.side
            when 'batting' then measured.hitter_played_days
            else measured.pitcher_played_days
        end as played_days,
        parts.numerator,
        parts.denominator,
        parts.replacement_numerator,
        parts.replacement_denominator
    from category_parts_pivoted as parts
    inner join scored_categories
        on scored_categories.category_key = parts.category_key
    inner join category_sides
        on category_sides.platform = parts.platform
        and category_sides.category_key = parts.category_key
    inner join measured
        on measured.transaction_id = parts.transaction_id

),

with_value as (

    select
        *,
        {{ fo_value_over_replacement(
            'numerator', 'denominator', 'played_days',
            'replacement_numerator', 'replacement_denominator', 'is_lower_better'
        ) }} as value_over_replacement
    from valued

),

-- The season fact's own spread, read rather than recomputed.
category_spread as (

    select
        category_key,
        stddev_pop(value_over_replacement) as standard_deviation
    from {{ ref('fct_player_category_value') }}
    where played_days > 0
    group by category_key

),

standardised as (

    select
        with_value.transaction_id,
        {{ fo_standardised_value(
            'with_value.value_over_replacement', 'with_value.played_days', 'category_spread.standard_deviation'
        ) }} as standardised_value
    from with_value
    left join category_spread
        on category_spread.category_key = with_value.category_key

),

total_values as (

    select
        transaction_id,
        case
            when count(*) filter (where standardised_value is null) > 0 then null
            else sum(standardised_value)
        end as total_value
    from standardised
    group by transaction_id

)

select
    measured.platform,
    measured.transaction_id,
    measured.topic_id,
    measured.transacted_at,
    measured.transaction_date,
    measured.platform_player_id,
    measured.fantasy_team_id,
    measured.movement,
    measured.method,
    measured.dropped_from_slot,
    measured.window_start,
    measured.window_end,
    measured.rostered_days,
    measured.started_days,
    measured.played_started_days,
    measured.played_days,
    measured.next_added_at,
    measured.next_added_by_team_id,
    {%- for column in component_columns %}
    measured.{{ column }},
    {%- endfor %}
    case
        when measured.movement = 'drop' and measured.replacement_group is null then null
        else total_values.total_value
    end as total_value
from measured
left join total_values
    on total_values.transaction_id = measured.transaction_id
