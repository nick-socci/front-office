-- Every category scored by a league-season with rosters has a rule in
-- int_fantasy__stat_components. Returns each one that has none.
--
-- A scored category with no rule never appears in the marts: the value models reach a
-- category through its rule, by inner join. This was a relationships test on
-- int_fantasy__categories.category_key and makes the same check, for covered
-- league-seasons only (ADR 0026): a past season loaded for its matchup totals may score a
-- category this project has no rule for (complete games, in 2018 and 2021), and needs
-- none while no value is computed for it. The day such a season's rosters are loaded it
-- is covered, and this fails until the rule exists.

select
    categories.platform,
    categories.league_id,
    categories.season,
    categories.category_key,
    categories.category_label
from {{ ref('int_fantasy__categories') }} as categories
inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
    on league_seasons.platform = categories.platform
    and league_seasons.league_id = categories.league_id
    and league_seasons.season = categories.season
    and league_seasons.has_rosters
where not exists (
    select 1
    from {{ ref('int_fantasy__stat_components') }} as rules
    where
        rules.platform = categories.platform
        and rules.stat_key = categories.category_key
)
