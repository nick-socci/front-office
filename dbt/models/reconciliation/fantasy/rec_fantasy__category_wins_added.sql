-- One row per (player, fantasy team): how many category results, and how many matchups,
-- actually went the team's way because of him. Every matchup he had a started day in is
-- scored again with his production taken out and replacement production put in its place,
-- and the results that change are counted.
--
-- This is a check, not a valuation (spec 0089). The value facts turn production into
-- "matchup margins" by a linear scale; this model uses no scale at all, only the rules
-- that score a category and the same replacement level. If the value facts are sound, a
-- unit of total_value buys the same number of real category wins whoever it belongs to:
-- about 0.40, because for a margin that is normal with the scale as its root mean square
-- a small contribution of x scale units moves the expected result by x / sqrt(2 * pi).
-- rec_fantasy__category_wins_by_group measures that per group of players, and
-- values_track_rescored_category_wins holds the facts to it. It is what showed, in 2026,
-- that the arithmetic was even-handed between starters and hitters and that the tilt
-- toward pitching was in the level a start was measured against (ADR 0029).
--
-- It lives with the reconciliation models because it sets our numbers against an
-- independent account of the same thing. It is not a mart: one player's figures are
-- noisy (a category flips or it does not), and it is read in aggregate.
--
-- WHICH MATCHUPS. Those fct_matchup_results gives a winner, with has_unverified_inputs
-- false: a result resting on a missing boxscore or an unresolved player is not a result
-- to score again. Playoffs included, since the values being checked count every started
-- day. A matchup in progress has a winner so far and is scored again as it stands.
--
-- THE SWAP, in components (AGENTS.md rule 4). The side's totals, minus the pair's started
-- production in the matchup, plus what replacement is expected to produce in the pair's
-- played days of each kind (a batting day, a start, a relief day: ADR 0008), by the
-- levels of int_fantasy__replacement_levels. Every scored category is then computed for
-- that side by the rules of int_fantasy__stat_components and judged against the
-- opponent's actual value, at 9 decimal places as fct_matchup_category_scores does.
--
-- WHOLE NUMBERS. Replacement's expected production is fractional: 0.25 wins a start, a
-- quarter of a steal a week. Real totals are whole, and many categories are close (14% of
-- stolen-base results are ties), so a fraction added to one side breaks every tie in its
-- category the same way. Measured in 2026, that alone moved the slopes from 0.41, 0.39
-- and 0.39 to 0.36, 0.32 and 0.46. So each expected amount is rounded down, and up with
-- probability equal to its fraction, twenty times, and the results averaged. The draw is
-- the first 32 bits of an MD5 of the pair, the matchup, the component and the draw's
-- number: the same on every build and on every version of the engine. Components are
-- drawn independently, so a draw is not a realistic box score; it does not need to be.
--
-- THE PITCHING MINIMUM. The category results, actual and rescored, are decided by
-- fo_category_result (ADR 0084), so the league-season's minimum applies as it does in the
-- fact. The rescored side is judged on its swapped outs: a swap that takes a side below the
-- minimum loses its bound categories (ADR 0083), however good the swapped values are.
--
-- A NULL LEVEL (an empty pool) for a kind of day the pair played in such a matchup makes
-- both measures null for the pair, as the value facts give it a null value, and the row
-- stays. A category undefined for the swapped side in a draw is left out of that draw,
-- unless the minimum decides it.
--
-- matchup_wins_added uses the league's rule as fct_matchup_results has it: more categories
-- won than lost is a win. Equal is a tie in the regular season, counted one half, and in a
-- playoff matchup it goes to the home side, the higher seed (ADR 0080, spec 0159): 1 for the
-- home side and 0 for the away side. The same rule scores the actual and the rescored
-- matchup, so a playoff tie is not a half on one side of the difference. A win counts 1
-- throughout. category_wins_added counts a tied category a half in every matchup.

{{ config(materialized='table') }}

{%- set draws = 20 %}
{%- set batting_columns = fo_batting_columns() %}
{%- set pitching_columns = fo_pitching_columns() %}
{#- A level matchup as the league scores it, for one side: a playoff tie goes to the home side. #}
{%- set level_matchup_score = (
    'case when is_playoff and is_home then 1.0 when is_playoff then 0 else 0.5 end'
) %}
{%- set pair_keys = [
    'platform',
    'league_id',
    'season',
    'matchup_id',
    'fantasy_team_id',
    'platform_player_id'
] %}
{%- set pitching_day_kind = fo_pitching_day_kind('days.games_pitched', 'days.games_started') %}
{#- The fields the draw hashes, in order, joined by '|'. None of them can be null (every key
    is under a not_null contract), so || gives what concat_ws gave. #}
{%- set draw_fields = [
    'pair_components.platform',
    'pair_components.league_id',
    'cast(pair_components.season as ' ~ fo_type_text() ~ ')',
    'cast(pair_components.matchup_id as ' ~ fo_type_text() ~ ')',
    'cast(pair_components.fantasy_team_id as ' ~ fo_type_text() ~ ')',
    'cast(pair_components.platform_player_id as ' ~ fo_type_text() ~ ')',
    'pair_components.component',
    'cast(draw_numbers.draw as ' ~ fo_type_text() ~ ')'
] %}

with rescorable_sides as (

    select
        sides.platform,
        sides.league_id,
        sides.season,
        sides.matchup_id,
        sides.matchup_period,
        sides.fantasy_team_id,
        sides.opponent_team_id,
        results.home_team_id = sides.fantasy_team_id as is_home,
        results.playoff_tier != 'NONE' as is_playoff
    from {{ ref('int_fantasy__matchup_sides') }} as sides
    inner join {{ ref('fct_matchup_results') }} as results
        on results.platform = sides.platform
        and results.league_id = sides.league_id
        and results.season = sides.season
        and results.matchup_id = sides.matchup_id
    where
        results.winner is not null
        and not results.has_unverified_inputs

),

-- The pair's started production in each matchup, and its played days of each kind.
pair_matchups as (

    select
        sides.platform,
        sides.league_id,
        sides.season,
        sides.matchup_id,
        sides.fantasy_team_id,
        sides.opponent_team_id,
        days.platform_player_id,
        count(
            case when days.slot_role = 'hitter' and days.games_batted > 0 then 1 end
        ) as batting_days,
        count(
            case
                when days.slot_role = 'pitcher' and {{ pitching_day_kind }} = 'start' then 1
            end
        ) as start_days,
        count(
            case
                when days.slot_role = 'pitcher' and {{ pitching_day_kind }} = 'relief' then 1
            end
        ) as relief_days,
        {%- for column in batting_columns + pitching_columns %}
        sum(coalesce(days.{{ column }}, 0)) as {{ column }}{% if not loop.last %},{% endif %}
        {%- endfor %}
    from {{ ref('int_fantasy__started_player_days') }} as days
    inner join {{ ref('int_fantasy__matchup_periods') }} as periods
        on periods.platform = days.platform
        and periods.league_id = days.league_id
        and periods.season = days.season
        and periods.scoring_date = days.scoring_date
    inner join rescorable_sides as sides
        on sides.platform = days.platform
        and sides.league_id = days.league_id
        and sides.season = days.season
        and sides.matchup_period = periods.matchup_period
        and sides.fantasy_team_id = days.fantasy_team_id
    group by
        sides.platform,
        sides.league_id,
        sides.season,
        sides.matchup_id,
        sides.fantasy_team_id,
        sides.opponent_team_id,
        days.platform_player_id

),

levels as (

    select
        platform,
        league_id,
        season,
        day_kind,
        component,
        level_per_played_day
    from {{ ref('int_fantasy__replacement_levels') }}

),

-- One row per (pair, matchup, component): what the pair produced, and what replacement is
-- expected to in the same played days. A kind the pair did not play charges nothing,
-- whatever its level; a kind it did play with a null level makes the expectation null.
pair_components as (

    {%- for column in batting_columns %}
    select
        {%- for key in pair_keys %}
        pair_matchups.{{ key }},
        {%- endfor %}
        '{{ column }}' as component,
        cast(pair_matchups.{{ column }} as {{ fo_type_float() }}) as pair_total,
        case
            when pair_matchups.batting_days = 0 then 0
            else pair_matchups.batting_days * batting.level_per_played_day
        end as replacement_expected
    from pair_matchups
    left join levels as batting
        on batting.platform = pair_matchups.platform
        and batting.league_id = pair_matchups.league_id
        and batting.season = pair_matchups.season
        and batting.day_kind = 'batting'
        and batting.component = '{{ column }}'
    union all
    {%- endfor %}
    {%- for column in pitching_columns %}
    select
        {%- for key in pair_keys %}
        pair_matchups.{{ key }},
        {%- endfor %}
        '{{ column }}' as component,
        cast(pair_matchups.{{ column }} as {{ fo_type_float() }}) as pair_total,
        case
            when pair_matchups.start_days = 0 then 0
            else pair_matchups.start_days * starts.level_per_played_day
        end
        + case
            when pair_matchups.relief_days = 0 then 0
            else pair_matchups.relief_days * relief.level_per_played_day
        end as replacement_expected
    from pair_matchups
    left join levels as starts
        on starts.platform = pair_matchups.platform
        and starts.league_id = pair_matchups.league_id
        and starts.season = pair_matchups.season
        and starts.day_kind = 'start'
        and starts.component = '{{ column }}'
    left join levels as relief
        on relief.platform = pair_matchups.platform
        and relief.league_id = pair_matchups.league_id
        and relief.season = pair_matchups.season
        and relief.day_kind = 'relief'
        and relief.component = '{{ column }}'
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

-- A pair is all or nothing: one unknown level leaves the whole pair unmeasured.
unmeasured_pairs as (

    select distinct
        platform,
        league_id,
        season,
        fantasy_team_id,
        platform_player_id
    from pair_components
    where replacement_expected is null

),

side_components as (

    {%- for column in batting_columns + pitching_columns %}
    select
        platform,
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        '{{ column }}' as component,
        cast({{ column }} as {{ fo_type_float() }}) as side_total
    from {{ ref('int_fantasy__matchup_side_totals') }}
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

draw_numbers as (

    -- 1 to `draws`, both included. The one-row relation is what the unnest is joined to.
    select draw  -- noqa: RF02
    from (select 1 as one) as one_row
    {{ fo_unnest(fo_int_series('1', draws), 'draw') }}

),

-- The side's totals with the pair swapped for a whole-number draw of replacement.
swapped_components as (

    select
        {%- for key in pair_keys %}
        pair_components.{{ key }},
        {%- endfor %}
        draw_numbers.draw,
        pair_components.component,
        side_components.side_total
        - pair_components.pair_total
        + floor(pair_components.replacement_expected)
        + case
            when
                cast(
                    '0x' || substr({{ fo_md5_hex(draw_fields | join(" || '|' || ")) }}, 1, 8)
                    as bigint
                ) / 4294967296.0
                < pair_components.replacement_expected - floor(pair_components.replacement_expected)
                then 1
            else 0
        end as swapped_total
    from pair_components
    cross join draw_numbers
    inner join side_components
        on side_components.platform = pair_components.platform
        and side_components.league_id = pair_components.league_id
        and side_components.season = pair_components.season
        and side_components.matchup_id = pair_components.matchup_id
        and side_components.fantasy_team_id = pair_components.fantasy_team_id
        and side_components.component = pair_components.component
    left join unmeasured_pairs
        on unmeasured_pairs.platform = pair_components.platform
        and unmeasured_pairs.league_id = pair_components.league_id
        and unmeasured_pairs.season = pair_components.season
        and unmeasured_pairs.fantasy_team_id = pair_components.fantasy_team_id
        and unmeasured_pairs.platform_player_id = pair_components.platform_player_id
    where unmeasured_pairs.platform_player_id is null

),

scored_rules as (

    select
        categories.platform,
        categories.league_id,
        categories.season,
        categories.category_key,
        categories.is_lower_better,
        categories.is_bound_by_minimum,
        rules.part,
        rules.component,
        rules.weight
    from {{ ref('int_fantasy__categories') }} as categories
    inner join {{ ref('int_fantasy__stat_components') }} as rules
        on rules.platform = categories.platform
        and rules.stat_key = categories.category_key

),

-- Each scored category's value for the swapped side, as int_fantasy__matchup_stat_values
-- computes it for a real one.
swapped_values as (

    select
        {%- for key in pair_keys %}
        swapped.{{ key }},
        {%- endfor %}
        swapped.draw,
        scored_rules.category_key,
        scored_rules.is_lower_better,
        scored_rules.is_bound_by_minimum,
        case
            when count(case when scored_rules.part = 'denominator' then 1 end) = 0
                then
                    -- order-exempt: whole weights of at most 10^6, held by
                    -- int_fantasy__stat_components_weights_are_whole, times whole swapped
                    -- totals in the hundreds: |sum| < 2e12, far below 2^53.
                    sum(
                        case
                            when scored_rules.part = 'numerator'
                                then scored_rules.weight * swapped.swapped_total
                        end
                    )
            else
                -- order-exempt: as above.
                sum(
                    case
                        when scored_rules.part = 'numerator'
                            then scored_rules.weight * swapped.swapped_total
                    end
                )
                / nullif(
                    -- order-exempt: as above.
                    sum(
                        case
                            when scored_rules.part = 'denominator'
                                then scored_rules.weight * swapped.swapped_total
                        end
                    ),
                    0
                )
        end as swapped_value
    from swapped_components as swapped
    inner join scored_rules
        on scored_rules.platform = swapped.platform
        and scored_rules.league_id = swapped.league_id
        and scored_rules.season = swapped.season
        and scored_rules.component = swapped.component
    group by
        {%- for key in pair_keys %}
        swapped.{{ key }},
        {%- endfor %}
        swapped.draw,
        scored_rules.category_key,
        scored_rules.is_lower_better,
        scored_rules.is_bound_by_minimum

),

-- The outs the swapped side records in each draw, for the pitching minimum. Every pair has
-- an outs_recorded row in swapped_components: it is one of the pitching columns.
swapped_outs as (

    select
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        draw,
        swapped_total as swapped_outs
    from swapped_components
    where component = 'outs_recorded'

),

actual_values as (

    select
        platform,
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        opponent_team_id,
        stat_key as category_key,
        round(stat_value, 9) as stat_value
    from {{ ref('int_fantasy__matchup_stat_values') }}

),

-- The category's result with the pair and with replacement, against the same opponent,
-- by fo_category_result: the pitching minimum first, each side's outs against it (the
-- swapped side's from swapped_outs), then the values. A result is null where the category
-- is undefined and the minimum does not decide it.
decided_results as (

    select
        {%- for key in pair_keys %}
        swapped.{{ key }},
        {%- endfor %}
        swapped.draw,
        swapped.category_key,
        {{ fo_category_result(
            'team.stat_value',
            'opponent.stat_value',
            'swapped.is_lower_better',
            'swapped.is_bound_by_minimum',
            'coalesce(team_totals.outs_recorded < seasons.pitching_minimum_outs, false)',
            'coalesce(opponent_totals.outs_recorded < seasons.pitching_minimum_outs, false)'
        ) }} as actual_result,
        {{ fo_category_result(
            'swapped.swapped_value',
            'opponent.stat_value',
            'swapped.is_lower_better',
            'swapped.is_bound_by_minimum',
            'coalesce(swapped_outs.swapped_outs < seasons.pitching_minimum_outs, false)',
            'coalesce(opponent_totals.outs_recorded < seasons.pitching_minimum_outs, false)'
        ) }} as swapped_result,
        side.is_home,
        side.is_playoff
    from swapped_values as swapped
    inner join swapped_outs
        on swapped_outs.platform = swapped.platform
        and swapped_outs.league_id = swapped.league_id
        and swapped_outs.season = swapped.season
        and swapped_outs.matchup_id = swapped.matchup_id
        and swapped_outs.fantasy_team_id = swapped.fantasy_team_id
        and swapped_outs.platform_player_id = swapped.platform_player_id
        and swapped_outs.draw = swapped.draw
    left join {{ ref('int_fantasy__league_seasons') }} as seasons
        on seasons.platform = swapped.platform
        and seasons.league_id = swapped.league_id
        and seasons.season = swapped.season
    inner join {{ ref('int_fantasy__matchup_side_totals') }} as team_totals
        on team_totals.platform = swapped.platform
        and team_totals.league_id = swapped.league_id
        and team_totals.season = swapped.season
        and team_totals.matchup_id = swapped.matchup_id
        and team_totals.fantasy_team_id = swapped.fantasy_team_id
    inner join rescorable_sides as side
        on side.platform = swapped.platform
        and side.league_id = swapped.league_id
        and side.season = swapped.season
        and side.matchup_id = swapped.matchup_id
        and side.fantasy_team_id = swapped.fantasy_team_id
    inner join actual_values as team
        on team.platform = swapped.platform
        and team.league_id = swapped.league_id
        and team.season = swapped.season
        and team.matchup_id = swapped.matchup_id
        and team.fantasy_team_id = swapped.fantasy_team_id
        and team.category_key = swapped.category_key
    inner join actual_values as opponent
        on opponent.platform = team.platform
        and opponent.league_id = team.league_id
        and opponent.season = team.season
        and opponent.matchup_id = team.matchup_id
        and opponent.fantasy_team_id = team.opponent_team_id
        and opponent.category_key = team.category_key
    inner join {{ ref('int_fantasy__matchup_side_totals') }} as opponent_totals
        on opponent_totals.platform = team.platform
        and opponent_totals.league_id = team.league_id
        and opponent_totals.season = team.season
        and opponent_totals.matchup_id = team.matchup_id
        and opponent_totals.fantasy_team_id = team.opponent_team_id

),

-- Undefined on any of the three sides, and not decided by the minimum: left out of this
-- draw. With no minimum that is a null value on any side; with one, a bound category the
-- minimum decides is kept even when a value is null.
category_results as (

    select *
    from decided_results
    where
        actual_result is not null
        and swapped_result is not null

),

matchup_draws as (

    select
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        draw,
        sum(case actual_result when 'WIN' then 1.0 when 'TIE' then 0.5 else 0 end)
        - sum(case swapped_result when 'WIN' then 1.0 when 'TIE' then 0.5 else 0 end)
            as category_wins_added,
        case
            when
                count(case when actual_result = 'WIN' then 1 end)
                > count(case when actual_result = 'LOSS' then 1 end) then 1.0
            when
                count(case when actual_result = 'WIN' then 1 end)
                = count(case when actual_result = 'LOSS' then 1 end) then {{ level_matchup_score }}
            else 0
        end
        - case
            when
                count(case when swapped_result = 'WIN' then 1 end)
                > count(case when swapped_result = 'LOSS' then 1 end) then 1.0
            when
                count(case when swapped_result = 'WIN' then 1 end)
                = count(case when swapped_result = 'LOSS' then 1 end) then {{ level_matchup_score }}
            else 0
        end as matchup_wins_added
    from category_results
    group by
        {%- for key in pair_keys %}
        {{ key }},
        {%- endfor %}
        draw,
        is_home,
        is_playoff

),

measured as (

    select
        platform,
        league_id,
        season,
        fantasy_team_id,
        platform_player_id,
        -- Summed in a fixed order: the last digit of a floating-point sum depends on the
        -- order of its terms, and row order changes from build to build.
        {{ fo_sum_in_order('category_wins_added', 'matchup_id, draw') }}
        / {{ draws }} as category_wins_added,
        {{ fo_sum_in_order('matchup_wins_added', 'matchup_id, draw') }}
        / {{ draws }} as matchup_wins_added
    from matchup_draws
    group by platform, league_id, season, fantasy_team_id, platform_player_id

),

pairs as (

    select
        platform,
        league_id,
        season,
        fantasy_team_id,
        platform_player_id,
        count(*) as matchups_rescored
    from pair_matchups
    group by platform, league_id, season, fantasy_team_id, platform_player_id

)

select
    pairs.platform,
    pairs.league_id,
    pairs.season,
    pairs.platform_player_id,
    pairs.fantasy_team_id,
    pairs.matchups_rescored,
    measured.category_wins_added,
    measured.matchup_wins_added
from pairs
left join measured
    on measured.platform = pairs.platform
    and measured.league_id = pairs.league_id
    and measured.season = pairs.season
    and measured.fantasy_team_id = pairs.fantasy_team_id
    and measured.platform_player_id = pairs.platform_player_id
