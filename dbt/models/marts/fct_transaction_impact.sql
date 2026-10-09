-- What each add or drop opened up, valued on the same scale as a player's season (#11).
-- One row per transaction. An add is valued by what the player did for the adding team
-- while it started him; a drop by what he did for the rest of the season, for whoever had
-- him: the cost of letting him go. Neither is a counterfactual about the lineup, only a
-- window of production measured against a free-agent replacement.
--
-- Carries league_id and season, like int_fantasy__transactions (#28), and every join and
-- window below stays inside them: the scoring bounds, the same team's next drop, the next
-- add, roster and started days, the replacement levels, the category scales and the scored
-- categories are all those of the transaction's own league-season. The MLBAM id and group
-- come from that league-season's row of dim_player_league_seasons, not from dim_players.
--
-- The window, both ends inclusive, from the first and last scoring dates of the
-- league-season's int_fantasy__matchup_periods:
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
-- A drop counts MLB days from int_mlb__player_game_days for his dim_player_league_seasons.mlbam_player_id,
-- on the side his replacement_group is credited for only (hitter: batting columns and
-- played_days = days with games_batted > 0; SP and RP: pitching columns and days with
-- games_pitched > 0); the other side is 0. rostered_days, started_days and
-- played_started_days are null on a drop, played_days is null on an add. A dropped player
-- with no MLBAM id or group is unresolved: zeroes, and a NULL total_value, because 0
-- would read as replacement level.
--
-- mlbam_player_id, the last column, is the MLB id of the transaction's own league-season
-- row (#60, ADR 0034), already carried here from dim_player_league_seasons; null when
-- unresolved.
--
-- total_value is on the scale of fct_player_category_value, in matchup margins (ADR 0010):
-- the same per-category arithmetic (the fo_category_value macros), the same replacement
-- levels and the same margin scale and side denominator, READ from
-- int_fantasy__category_scales, never recomputed over transactions, or a two-week window
-- and a season would not be comparable. The scales are joined on platform, league, season
-- and category_key. Which matchups they were measured from is that model's business (ADR
-- 0027): with earlier seasons loaded, a blend of them and the season's decided matchups.
--
-- KIND OF DAY (ADR 0008, #52), as in fct_player_category_value. A window's played days are
-- grouped by kind and each kind is valued against its own replacement level: `batting` (a
-- hitter-side day with games_batted > 0), `start` or `relief` (a pitching-side day, by
-- fo_pitching_day_kind from that day's own games_pitched and games_started). A start is
-- compared with what a free agent produced in a start, a relief day with what one produced
-- in relief. On an add the days are the window's started days of that player for that team,
-- the side of each being its slot's; on a drop they are his MLB days, the side being the
-- one his dim_player_league_seasons.replacement_group credits (hitter, or pitcher for SP and RP). That
-- group now only tells a hitter from a pitcher: SP versus RP chooses nothing, the outing
-- does. A day that is not a played day on its side belongs to no kind and adds nothing.
--
-- Per (transaction, category) the values of the kinds on the category's side are summed:
-- NULL if ANY kind with played days has a null value (a null level, an empty pool), because
-- a plain sum skips nulls and would report a partial value as complete. A category with no
-- played day on its side is worth 0. Scaling and the sum over every scored category
-- (NULL if any is NULL) are as before. The wide component columns and the day counts stay
-- whole-window totals; only total_value is valued per kind.

{{ config(materialized='table') }}

{%- set batting_columns = fo_batting_columns() %}
{%- set pitching_columns = fo_pitching_columns() %}
{%- set component_columns = batting_columns + pitching_columns %}

with scoring_bounds as (

    select
        platform,
        league_id,
        season,
        min(scoring_date) as first_scoring_date,
        max(scoring_date) as last_scoring_date
    from {{ ref('int_fantasy__matchup_periods') }}
    group by platform, league_id, season

),

transactions as (

    select * from {{ ref('int_fantasy__transactions') }}

),

-- For each add, the date of the same team's earliest later drop of the same player.
next_team_drops as (

    select
        adds.platform,
        adds.league_id,
        adds.season,
        adds.transaction_id,
        min(drops.transaction_date) as next_drop_date
    from transactions as adds
    inner join transactions as drops
        on drops.platform = adds.platform
        and drops.league_id = adds.league_id
        and drops.season = adds.season
        and drops.platform_player_id = adds.platform_player_id
        and drops.fantasy_team_id = adds.fantasy_team_id
        and drops.movement = 'drop'
        and drops.transacted_at > adds.transacted_at
    where adds.movement = 'add'
    group by adds.platform, adds.league_id, adds.season, adds.transaction_id

),

windows as (

    select
        transactions.*,
        players.mlbam_player_id,
        players.replacement_group,
        case transactions.movement
            when 'add' then greatest(transactions.transaction_date, bounds.first_scoring_date)
            when 'drop' then greatest(transactions.transaction_date + 1, bounds.first_scoring_date)
        end as window_start,
        case transactions.movement
            when 'add' then coalesce(next_team_drops.next_drop_date, bounds.last_scoring_date)
            when 'drop' then bounds.last_scoring_date
        end as window_end
    from transactions
    left join scoring_bounds as bounds
        on bounds.platform = transactions.platform
        and bounds.league_id = transactions.league_id
        and bounds.season = transactions.season
    left join next_team_drops
        on next_team_drops.platform = transactions.platform
        and next_team_drops.league_id = transactions.league_id
        and next_team_drops.season = transactions.season
        and next_team_drops.transaction_id = transactions.transaction_id
    left join {{ ref('dim_player_league_seasons') }} as players
        on players.platform = transactions.platform
        and players.league_id = transactions.league_id
        and players.season = transactions.season
        and players.platform_player_id = transactions.platform_player_id

),

add_rostered as (

    select
        windows.platform,
        windows.league_id,
        windows.season,
        windows.transaction_id,
        count(*) as rostered_days
    from windows
    inner join {{ ref('int_fantasy__roster_days') }} as days
        on days.platform = windows.platform
        and days.league_id = windows.league_id
        and days.season = windows.season
        and days.platform_player_id = windows.platform_player_id
        and days.fantasy_team_id = windows.fantasy_team_id
        and days.scoring_date between windows.window_start and windows.window_end
    where windows.movement = 'add'
    group by windows.platform, windows.league_id, windows.season, windows.transaction_id

),

add_started as (

    select
        windows.platform,
        windows.league_id,
        windows.season,
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
        and days.league_id = windows.league_id
        and days.season = windows.season
        and days.platform_player_id = windows.platform_player_id
        and days.fantasy_team_id = windows.fantasy_team_id
        and days.scoring_date between windows.window_start and windows.window_end
    where windows.movement = 'add'
    group by windows.platform, windows.league_id, windows.season, windows.transaction_id

),

-- A drop's MLB days, only on the side his group is credited for.
drop_games as (

    select
        windows.platform,
        windows.league_id,
        windows.season,
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
    group by windows.platform, windows.league_id, windows.season, windows.transaction_id

),

-- The earliest add of the player by any team after each drop; transaction_id breaks a tie
-- in transacted_at.
next_adds as (

    select
        platform,
        league_id,
        season,
        transaction_id,
        next_added_at,
        next_added_by_team_id
    from (
        select
            drops.platform,
            drops.league_id,
            drops.season,
            drops.transaction_id,
            adds.transacted_at as next_added_at,
            adds.fantasy_team_id as next_added_by_team_id,
            row_number() over (
                partition by drops.platform, drops.league_id, drops.season, drops.transaction_id
                order by adds.transacted_at, adds.transaction_id
            ) as add_rank
        from transactions as drops
        inner join transactions as adds
            on adds.platform = drops.platform
            and adds.league_id = drops.league_id
            and adds.season = drops.season
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
        next_adds.next_added_at,
        next_adds.next_added_by_team_id,
        {%- for column in component_columns %}
        coalesce(add_started.{{ column }}, drop_games.{{ column }}, 0) as {{ column }}{{ ',' if not loop.last }}
        {%- endfor %}
    from windows
    left join add_rostered
        on add_rostered.platform = windows.platform
        and add_rostered.league_id = windows.league_id
        and add_rostered.season = windows.season
        and add_rostered.transaction_id = windows.transaction_id
    left join add_started
        on add_started.platform = windows.platform
        and add_started.league_id = windows.league_id
        and add_started.season = windows.season
        and add_started.transaction_id = windows.transaction_id
    left join drop_games
        on drop_games.platform = windows.platform
        and drop_games.league_id = windows.league_id
        and drop_games.season = windows.season
        and drop_games.transaction_id = windows.transaction_id
    left join next_adds
        on next_adds.platform = windows.platform
        and next_adds.league_id = windows.league_id
        and next_adds.season = windows.season
        and next_adds.transaction_id = windows.transaction_id

),

-- Each add's started days with their kind. A started day that is not a played day on its
-- slot's side has no kind and is dropped here.
add_kinded_days as (

    select
        windows.platform,
        windows.league_id,
        windows.season,
        windows.transaction_id,
        case days.slot_role
            when 'hitter' then case when days.games_batted > 0 then 'batting' end
            when 'pitcher' then {{ fo_pitching_day_kind('days.games_pitched', 'days.games_started') }}
        end as day_kind,
        {%- for column in component_columns %}
        days.{{ column }}{{ ',' if not loop.last }}
        {%- endfor %}
    from windows
    inner join {{ ref('int_fantasy__started_player_days') }} as days
        on days.platform = windows.platform
        and days.league_id = windows.league_id
        and days.season = windows.season
        and days.platform_player_id = windows.platform_player_id
        and days.fantasy_team_id = windows.fantasy_team_id
        and days.scoring_date between windows.window_start and windows.window_end
    where windows.movement = 'add'

),

-- Each drop's MLB days with their kind, on the side his group is credited for only.
drop_kinded_days as (

    select
        windows.platform,
        windows.league_id,
        windows.season,
        windows.transaction_id,
        case
            when windows.replacement_group = 'hitter'
                then case when games.games_batted > 0 then 'batting' end
            when windows.replacement_group in ('SP', 'RP')
                then {{ fo_pitching_day_kind('games.games_pitched', 'games.games_started') }}
        end as day_kind,
        {%- for column in component_columns %}
        games.{{ column }}{{ ',' if not loop.last }}
        {%- endfor %}
    from windows
    inner join {{ ref('int_mlb__player_game_days') }} as games
        on games.mlbam_player_id = windows.mlbam_player_id
        and games.game_date between windows.window_start and windows.window_end
    where windows.movement = 'drop'

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

-- One row per (transaction, kind): the played days of that kind and the component totals.
kind_days as (

    select
        platform,
        league_id,
        season,
        transaction_id,
        day_kind,
        count(*) as played_days,
        {%- for column in component_columns %}
        coalesce(sum({{ column }}), 0) as {{ column }}{{ ',' if not loop.last }}
        {%- endfor %}
    from (
        select platform, league_id, season, transaction_id, day_kind, {{ component_columns | join(', ') }} from add_kinded_days
        union all
        select platform, league_id, season, transaction_id, day_kind, {{ component_columns | join(', ') }} from drop_kinded_days
    )
    where day_kind is not null
    group by platform, league_id, season, transaction_id, day_kind

),

-- One row per (transaction, kind, component): the component's total over the window's days
-- of that kind. One query per component rather than a pivot, as the season fact does.
kind_component_totals as (

    {%- for column in component_columns %}
    select
        platform,
        league_id,
        season,
        transaction_id,
        day_kind,
        '{{ column }}' as component,
        cast({{ column }} as double) as component_total
    from kind_days
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

-- The weighted sums per (transaction, kind, stat, part): what the window held on days of
-- that kind, and what a replacement would have done per played day of that kind. A null
-- level anywhere makes the replacement null; a plain sum would skip it.
kind_parts as (

    select
        totals.platform,
        totals.league_id,
        totals.season,
        totals.transaction_id,
        totals.day_kind,
        rules.stat_key as category_key,
        rules.part,
        sum(rules.weight * totals.component_total) as part_total,
        case
            when bool_or(levels.level_per_played_day is null) then null
            else sum(rules.weight * levels.level_per_played_day order by rules.component)
        end as part_replacement
    from kind_component_totals as totals
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.component = totals.component
    inner join component_sides as sides
        on sides.component = totals.component
        -- a kind meets only the components of its own side
        and sides.side = case totals.day_kind when 'batting' then 'batting' else 'pitching' end
    left join {{ ref('int_fantasy__replacement_levels') }} as levels
        on levels.platform = totals.platform
        and levels.league_id = totals.league_id
        and levels.season = totals.season
        and levels.component = totals.component
        and levels.day_kind = totals.day_kind
    group by totals.platform, totals.league_id, totals.season, totals.transaction_id, totals.day_kind, rules.stat_key, rules.part

),

kind_parts_pivoted as (

    select
        platform,
        league_id,
        season,
        transaction_id,
        day_kind,
        category_key,
        max(part_total) filter (where part = 'numerator') as numerator,
        max(part_total) filter (where part = 'denominator') as denominator,
        max(part_replacement) filter (where part = 'numerator') as replacement_numerator,
        max(part_replacement) filter (where part = 'denominator') as replacement_denominator
    from kind_parts
    group by platform, league_id, season, transaction_id, day_kind, category_key

),

-- A category is a rate if it has a denominator part, derived as fct_player_category_value
-- does. One set per league-season: each scores its own categories.
scored_categories as (

    select
        categories.platform,
        categories.league_id,
        categories.season,
        categories.category_key,
        categories.is_lower_better,
        coalesce(bool_or(rules.part = 'denominator'), false) as is_rate
    from {{ ref('int_fantasy__categories') }} as categories
    left join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.stat_key = categories.category_key
    group by
        categories.platform, categories.league_id, categories.season,
        categories.category_key, categories.is_lower_better

),

-- One row per (transaction, kind, category) with that kind's value over replacement.
kind_values as (

    select
        parts.platform,
        parts.league_id,
        parts.season,
        parts.transaction_id,
        parts.category_key,
        kind_days.played_days,
        {{ fo_value_over_replacement(
            'parts.numerator', 'parts.denominator', 'kind_days.played_days',
            'parts.replacement_numerator', 'parts.replacement_denominator', 'scored_categories.is_lower_better'
        ) }} as value_over_replacement
    from kind_parts_pivoted as parts
    inner join scored_categories
        on scored_categories.platform = parts.platform
        and scored_categories.league_id = parts.league_id
        and scored_categories.season = parts.season
        and scored_categories.category_key = parts.category_key
    inner join kind_days
        on kind_days.platform = parts.platform
        and kind_days.league_id = parts.league_id
        and kind_days.season = parts.season
        and kind_days.transaction_id = parts.transaction_id
        and kind_days.day_kind = parts.day_kind

),

-- The sum over kinds for each (transaction, category) the window has a played day in. The
-- value is null if any kind's value is null.
summed_over_kinds as (

    select
        platform,
        league_id,
        season,
        transaction_id,
        category_key,
        cast(sum(played_days) as bigint) as played_days,
        case
            when bool_or(value_over_replacement is null) then null
            else sum(value_over_replacement)
        end as value_over_replacement
    from kind_values
    group by platform, league_id, season, transaction_id, category_key

),

-- Every transaction crossed with every scored category, the summed values left-joined on:
-- a window with no played day on a category's side is worth 0 there, not absent.
with_value as (

    select
        measured.platform,
        measured.league_id,
        measured.season,
        measured.transaction_id,
        scored_categories.category_key,
        coalesce(summed.played_days, 0) as played_days,
        case
            when summed.category_key is null then 0
            else summed.value_over_replacement
        end as value_over_replacement
    from measured
    inner join scored_categories
        on scored_categories.platform = measured.platform
        and scored_categories.league_id = measured.league_id
        and scored_categories.season = measured.season
    left join summed_over_kinds as summed
        on summed.platform = measured.platform
        and summed.league_id = measured.league_id
        and summed.season = measured.season
        and summed.transaction_id = measured.transaction_id
        and summed.category_key = scored_categories.category_key

),

-- Each value divided by its category's scale, read from int_fantasy__category_scales as the
-- season fact does. A LEFT join: a category with no scale is worth 0 by the macro's rules,
-- not dropped. Scale and category are those of the transaction's own league-season.
scaled as (

    select
        with_value.platform,
        with_value.league_id,
        with_value.season,
        with_value.transaction_id,
        with_value.category_key,
        {{ fo_scaled_value(
            'with_value.value_over_replacement', 'with_value.played_days',
            'scales.margin_scale', 'scales.side_denominator', 'scored_categories.is_rate'
        ) }} as scaled_value
    from with_value
    inner join scored_categories
        on scored_categories.platform = with_value.platform
        and scored_categories.league_id = with_value.league_id
        and scored_categories.season = with_value.season
        and scored_categories.category_key = with_value.category_key
    left join {{ ref('int_fantasy__category_scales') }} as scales
        on scales.platform = with_value.platform
        and scales.league_id = with_value.league_id
        and scales.season = with_value.season
        and scales.category_key = with_value.category_key

),

total_values as (

    select
        platform,
        league_id,
        season,
        transaction_id,
        case
            when count(*) filter (where scaled_value is null) > 0 then null
            -- in category order: a sum of doubles is only reproducible in a fixed order (#28)
            else sum(scaled_value order by category_key)
        end as total_value
    from scaled
    group by platform, league_id, season, transaction_id

)

select
    measured.platform,
    measured.league_id,
    measured.season,
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
    end as total_value,
    measured.mlbam_player_id
from measured
left join total_values
    on total_values.platform = measured.platform
    and total_values.league_id = measured.league_id
    and total_values.season = measured.season
    and total_values.transaction_id = measured.transaction_id
