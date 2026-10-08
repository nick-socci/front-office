-- Every decided matchup has ESPN's total, on both sides, for every category its
-- league-season scores. Returns each (matchup, side, category) with no score.
--
-- For every league-season, with or without rosters. A past season is loaded for exactly
-- these totals (spec 0085, R5.4), and nothing else in the build reads them for a season
-- with no rosters, so a response that parsed to matchups with no totals, or to totals
-- for some categories only, would otherwise pass as a landed season. Spined on the
-- matchup and the scored categories, not on the results, so a missing row is found and
-- not just a null one.
--
-- A matchup ESPN has not decided is left out: during a season the current matchup's
-- totals are still moving. A season with no decided matchup at all returns nothing
-- here; the run evidence of a landing counts them per season (R5.5).

with decided_sides as (

    {%- for side in ['home', 'away'] %}
    select league_id, season, matchup_id, {{ side }}_team_id as team_id
    from {{ ref('stg_espn__matchups') }}
    where winner != 'UNDECIDED'
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

expected as (

    select
        decided_sides.league_id,
        decided_sides.season,
        decided_sides.matchup_id,
        decided_sides.team_id,
        categories.stat_id
    from decided_sides
    inner join {{ ref('stg_espn__scoring_categories') }} as categories
        on categories.league_id = decided_sides.league_id
        and categories.season = decided_sides.season

)

select
    expected.league_id,
    expected.season,
    expected.matchup_id,
    expected.team_id,
    expected.stat_id
from expected
left join {{ ref('stg_espn__matchup_category_results') }} as results
    on results.league_id = expected.league_id
    and results.season = expected.season
    and results.matchup_id = expected.matchup_id
    and results.team_id = expected.team_id
    and results.stat_id = expected.stat_id
where results.score is null
