-- int_fantasy__matchup_side_totals holds every side of every matchup of a league-season
-- with rosters, no more and no fewer. Returns each side present at one end only.
--
-- The model is built with left joins so that a side that started nobody keeps a row of
-- zeroes; an inner join slipped in below the sides would drop such a side without a
-- word, and its opponent would win every category against nothing. This was a row-count
-- comparison with int_fantasy__matchup_sides. It is now made side by side, and against
-- the sides of league-seasons with rosters only (ADR 0026): a season loaded for its
-- matchup totals alone has sides and, by design, no totals of ours.

with covered_sides as (

    select
        sides.platform,
        sides.league_id,
        sides.season,
        sides.matchup_id,
        sides.fantasy_team_id
    from {{ ref('int_fantasy__matchup_sides') }} as sides
    inner join {{ ref('int_fantasy__league_seasons') }} as league_seasons
        on league_seasons.platform = sides.platform
        and league_seasons.league_id = sides.league_id
        and league_seasons.season = sides.season
        and league_seasons.has_rosters

)

select
    coalesce(covered_sides.league_id, totals.league_id) as league_id,
    coalesce(covered_sides.season, totals.season) as season,
    coalesce(covered_sides.matchup_id, totals.matchup_id) as matchup_id,
    coalesce(covered_sides.fantasy_team_id, totals.fantasy_team_id) as fantasy_team_id,
    case when totals.matchup_id is null then 'no totals' else 'not a side of a covered season' end
        as problem
from covered_sides
full outer join {{ ref('int_fantasy__matchup_side_totals') }} as totals
    on totals.platform = covered_sides.platform
    and totals.league_id = covered_sides.league_id
    and totals.season = covered_sides.season
    and totals.matchup_id = covered_sides.matchup_id
    and totals.fantasy_team_id = covered_sides.fantasy_team_id
where covered_sides.matchup_id is null
    or totals.matchup_id is null
