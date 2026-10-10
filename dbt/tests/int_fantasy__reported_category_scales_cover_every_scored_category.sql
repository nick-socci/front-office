-- Every scored category of every league-season loaded has exactly one row in
-- int_fantasy__reported_category_scales, measured or not. Returns each category on one
-- side and not the other.
--
-- The model exists so that a league-season with nothing measured is seen as rows of
-- zero. Catches the spine becoming an inner join, which would make an unplayed season,
-- or a rate with no reported denominator, vanish instead (spec 0057, R2.1).

select
    coalesce(categories.league_id, scales.league_id) as league_id,
    coalesce(categories.season, scales.season) as season,
    coalesce(categories.category_key, scales.category_key) as category_key
from {{ ref('int_fantasy__categories') }} as categories
full outer join {{ ref('int_fantasy__reported_category_scales') }} as scales
    on scales.platform = categories.platform
    and scales.league_id = categories.league_id
    and scales.season = categories.season
    and scales.category_key = categories.category_key
where
    categories.category_key is null
    or scales.category_key is null
