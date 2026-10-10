-- The categories in fct_player_category_value must be exactly those of
-- int_fantasy__categories: none missing, none extra. Returns each category present on only
-- one side, with which one.
--
-- Catches a category list hardcoded or dropped somewhere in the build (R4.2): a stat whose
-- components are missing from int_fantasy__stat_components would simply vanish from the
-- fact through an inner join, and a count of rows alone would not say which.
--
-- The categories are those of league-seasons with rosters (ADR 0026): the fact starts from
-- started days, so a season loaded for its matchup totals alone has categories and no row
-- in the fact. For a league-season with rosters the check is what it was.

with in_fact as (

    select distinct
        platform,
        league_id,
        season,
        category_key
    from {{ ref('fct_player_category_value') }}

),

in_categories as (

    select
        categories.platform,
        categories.league_id,
        categories.season,
        categories.category_key
    from {{ ref('int_fantasy__categories') }} as categories
    inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
        on league_seasons.platform = categories.platform
        and league_seasons.league_id = categories.league_id
        and league_seasons.season = categories.season
        and league_seasons.has_rosters

)

select
    coalesce(in_fact.category_key, in_categories.category_key) as category_key,
    case
        when in_fact.category_key is null then 'missing from the fact' else 'not a scored category'
    end
        as problem
from in_fact
full outer join in_categories
    on in_categories.platform = in_fact.platform
    and in_categories.league_id = in_fact.league_id
    and in_categories.season = in_fact.season
    and in_categories.category_key = in_fact.category_key
where
    in_fact.category_key is null
    or in_categories.category_key is null
