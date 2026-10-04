-- The scales must hold exactly the categories the league scores: no more, no fewer.
-- Returns any category on one side and not the other.
--
-- Catches a scored category dropped from the scales (an inner join, or a list that
-- stopped at the categories someone remembered) and a category the league does not score
-- that a hardcoded list added.

select
    coalesce(categories.category_key, scales.category_key) as category_key
from {{ ref('int_fantasy__categories') }} as categories
full outer join {{ ref('int_fantasy__category_scales') }} as scales
    on scales.platform = categories.platform
    and scales.league_id = categories.league_id
    and scales.season = categories.season
    and scales.category_key = categories.category_key
where categories.category_key is null
    or scales.category_key is null
