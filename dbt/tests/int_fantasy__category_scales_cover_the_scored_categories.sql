-- The scales must hold exactly the categories the league scores: no more, no fewer.
-- Returns any category on one side and not the other.
--
-- Catches a scored category dropped from the scales (an inner join, or a list that
-- stopped at the categories someone remembered) and a category the league does not score
-- that a hardcoded list added.
--
-- The categories are those of league-seasons with rosters (ADR 0026), as the scales are:
-- a season loaded for its matchup totals alone has scored categories and no scale. For a
-- league-season with rosters the check is what it was, in both directions.

with categories as (

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

select coalesce(categories.category_key, scales.category_key) as category_key
from categories
full outer join {{ ref('int_fantasy__category_scales') }} as scales
    on scales.platform = categories.platform
    and scales.league_id = categories.league_id
    and scales.season = categories.season
    and scales.category_key = categories.category_key
where
    categories.category_key is null
    or scales.category_key is null
