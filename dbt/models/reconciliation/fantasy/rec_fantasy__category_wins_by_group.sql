-- One row per league-season and replacement group (hitter, SP, RP): how many real category
-- wins a unit of total_value bought, and whether the group is judged on it.
--
-- slope is the least-squares slope through the origin of category_wins_added on
-- total_value over the group's pairs: sum(wins * value) / sum(value^2). Theory puts it at
-- 1 / sqrt(2 * pi) = 0.399 for every group, and what matters is that groups agree: scaling
-- one group's values by a factor f divides its slope by f, so a group whose values are
-- inflated shows a low slope. See rec_fantasy__category_wins_added for where the wins
-- come from.
--
-- A group is judged when there is enough to judge it on: the league-season has at least
-- 100 matchups scored again, the group at least 100 pairs, and its two measures correlate
-- at 0.75 or more. In 2026 that is starters (0.85) and hitters (0.81) and not relievers
-- (0.69), whose values are the model's known weak spot (ADR 0009). The exclusion is by the
-- measure, not by name: a relief group whose values came to track real wins would be
-- judged with no change here (owner, 2026-10-09).
--
-- Every group is a row, judged or not, so that an unjudged group's figures are on record
-- and quoted in the run evidence. pairs_unmeasured counts pairs with a null value or null
-- wins added (an empty replacement pool): the slope is over the rest, and
-- values_track_rescored_category_wins fails a group of 100 or more pairs that has any, so
-- a slope from part of a group is never taken as the group's.

-- A view, so that it is never older than the values and the wins it compares: a table
-- would keep the slope of the last time it was built, and the test would judge that.
{{ config(materialized='view') }}

with matchups as (

    select platform, league_id, season, count(*) as matchups_rescored
    from {{ ref('fct_matchup_results') }}
    where winner is not null
        and not has_unverified_inputs
    group by platform, league_id, season

),

pairs as (

    select
        wins.platform,
        wins.league_id,
        wins.season,
        players.replacement_group,
        wins.platform_player_id,
        wins.fantasy_team_id,
        wins.category_wins_added,
        season_values.total_value
    from {{ ref('rec_fantasy__category_wins_added') }} as wins
    inner join {{ ref('dim_player_league_seasons') }} as players
        on players.platform = wins.platform
        and players.league_id = wins.league_id
        and players.season = wins.season
        and players.platform_player_id = wins.platform_player_id
    inner join {{ ref('fct_player_season_value') }} as season_values
        on season_values.platform = wins.platform
        and season_values.league_id = wins.league_id
        and season_values.season = wins.season
        and season_values.platform_player_id = wins.platform_player_id
        and season_values.fantasy_team_id = wins.fantasy_team_id

),

groups as (

    select
        platform,
        league_id,
        season,
        replacement_group,
        count(*) as pairs,
        count(*) filter (
            where category_wins_added is null or total_value is null
        ) as pairs_unmeasured,
        -- In a fixed order, as every floating-point sum here is.
        sum(category_wins_added * total_value order by platform_player_id, fantasy_team_id)
            / nullif(
                sum(total_value * total_value order by platform_player_id, fantasy_team_id)
                    filter (where category_wins_added is not null),
                0
            ) as slope,
        corr(category_wins_added, total_value) as correlation
    from pairs
    group by platform, league_id, season, replacement_group

)

select
    groups.platform,
    groups.league_id,
    groups.season,
    groups.replacement_group,
    matchups.matchups_rescored,
    groups.pairs,
    groups.pairs_unmeasured,
    groups.slope,
    groups.correlation,
    coalesce(
        matchups.matchups_rescored >= 100
            and groups.pairs >= 100
            and groups.correlation >= 0.75,
        false
    ) as is_judged,
    -- What values_track_rescored_category_wins fails on, decided here so that unit tests
    -- can reach it. An unmeasured pair fails a group of 100 pairs however many matchups
    -- there were (R3.8); the slope is judged only where is_judged says there is enough.
    case
        when groups.pairs >= 100 and groups.pairs_unmeasured > 0
            then 'not checkable: a pair has no value or no wins added'
        when matchups.matchups_rescored >= 100
            and groups.pairs >= 100
            and groups.correlation >= 0.75
            and (groups.slope < 0.34 or groups.slope > 0.47)
            then 'slope outside 0.34 to 0.47'
    end as problem
from groups
inner join matchups
    on matchups.platform = groups.platform
    and matchups.league_id = groups.league_id
    and matchups.season = groups.season
