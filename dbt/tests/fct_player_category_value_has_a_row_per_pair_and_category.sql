-- fct_player_category_value must hold exactly one row per (pair, scored category), where a
-- pair is a (player, fantasy team) with at least one started day. Returns the expected and
-- actual counts when they differ.
--
-- Catches fan-out from a join (more rows than pairs x categories) and pairs or categories
-- lost to one (fewer). The unique test says no duplicates; this says no gaps.

with pairs as (

    select distinct platform, league_id, season, platform_player_id, fantasy_team_id
    from {{ ref('int_fantasy__started_player_days') }}

),

expected as (

    select count(*) as expected_rows
    from pairs
    inner join {{ ref('int_fantasy__categories') }} as categories
        on categories.platform = pairs.platform
        and categories.league_id = pairs.league_id
        and categories.season = pairs.season

),

actual as (

    select count(*) as actual_rows
    from {{ ref('fct_player_category_value') }}

)

select expected_rows, actual_rows
from expected
cross join actual
where expected_rows <> actual_rows
