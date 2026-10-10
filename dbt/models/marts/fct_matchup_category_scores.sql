-- One row per (matchup, team, scored category): the team's value, its opponent's, and
-- who won the category.
--
-- The scored categories come from int_fantasy__categories, and their formulas from
-- int_fantasy__stat_components -- nothing here knows this league scores 17 categories
-- or what ERA is. A different league is a different seed.
--
-- The comparison is at 9 decimal places. Counts are exact either way; for rates it
-- stops float noise deciding a category: two sides with 9 ER in 27 outs and 6 ER in 18
-- outs have the same ERA, and must tie even if the two divisions disagree in the 16th
-- digit.
--
-- A null value (a rate over a zero denominator) gives a null result instead of a
-- guess. On a side with unverified inputs that is expected -- a missing boxscore can
-- leave a side with no outs -- and has_unverified_inputs already says so. On a verified
-- side it would mean a rule ESPN has never shown us, so the not_null test on result
-- stops the build there. 2026 has no such side.
--
-- A full rebuild, not incremental. Roster, boxscore and id-map corrections can change
-- closed periods, and nothing yet proves an incremental build equals a full one or
-- picks up a late correction (review, 2026-09-27). At ~5,000 rows a rebuild is free.

{{ config(materialized='table') }}

with side_values as (

    select
        stat_values.platform,
        stat_values.league_id,
        stat_values.season,
        stat_values.matchup_id,
        stat_values.matchup_period,
        stat_values.fantasy_team_id,
        stat_values.opponent_team_id,
        stat_values.is_home,
        categories.category_key,
        categories.category_label,
        categories.is_lower_better,
        stat_values.stat_value
    from {{ ref('int_fantasy__matchup_stat_values') }} as stat_values
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = stat_values.platform
        and categories.league_id = stat_values.league_id
        and categories.season = stat_values.season
        and categories.category_key = stat_values.stat_key

),

compared as (

    select
        team.*,
        opponent.stat_value as opponent_value,
        round(team.stat_value, 9) as team_rounded,
        round(opponent.stat_value, 9) as opponent_rounded
    from side_values as team
    inner join side_values as opponent
        on opponent.platform = team.platform
        and opponent.league_id = team.league_id
        and opponent.season = team.season
        and opponent.matchup_id = team.matchup_id
        and opponent.fantasy_team_id = team.opponent_team_id
        and opponent.category_key = team.category_key

)

select
    compared.platform,
    compared.league_id,
    compared.season,
    compared.matchup_id,
    compared.matchup_period,
    compared.fantasy_team_id,
    compared.opponent_team_id,
    compared.is_home,
    compared.category_key,
    compared.category_label,
    compared.is_lower_better,
    compared.stat_value as team_value,
    compared.opponent_value,
    case
        when compared.team_rounded is null or compared.opponent_rounded is null then null
        when compared.team_rounded = compared.opponent_rounded then 'TIE'
        when (compared.team_rounded < compared.opponent_rounded) = compared.is_lower_better
            then 'WIN'
        else 'LOSS'
    end as result,
    -- A category is only as certain as both sides' inputs.
    (
        team_totals.verified_player_days < team_totals.started_player_days
        or opponent_totals.verified_player_days < opponent_totals.started_player_days)
        as has_unverified_inputs
from compared
inner join {{ ref('int_fantasy__matchup_side_totals') }} as team_totals
    on team_totals.platform = compared.platform
    and team_totals.league_id = compared.league_id
    and team_totals.season = compared.season
    and team_totals.matchup_id = compared.matchup_id
    and team_totals.fantasy_team_id = compared.fantasy_team_id
inner join {{ ref('int_fantasy__matchup_side_totals') }} as opponent_totals
    on opponent_totals.platform = compared.platform
    and opponent_totals.league_id = compared.league_id
    and opponent_totals.season = compared.season
    and opponent_totals.matchup_id = compared.matchup_id
    and opponent_totals.fantasy_team_id = compared.opponent_team_id
