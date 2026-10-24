-- Every side of a played matchup has ESPN's matchup lines. Returns each side that has none.
--
-- The reconciliation reads these lines as ESPN's own record of what each side was credited
-- with (spec 0147, R2 and R5). A side without them is read as "no evidence", and a count
-- ESPN's lines would have explained stays unexplained, with nothing saying why. So a played
-- side with no lines is a finding about the capture, not something to carry silently:
-- the capture of its matchup period's last scoring period is missing, was asked for
-- another period (spec 0147, C1), or the model dropped its entries.
--
-- Played: a side of a matchup ESPN has decided (stg_espn__matchups, byes already out).
-- Covered: a league-season with rosters (ADR 0026) whose matchup-days captures are
-- landed, i.e. that stg_espn__matchup_days holds rows for. A season with rosters and no
-- matchup-days capture at all (a league that never fetched them) is not judged
-- here: its lack is stg_espn__matchup_days_mark_one_period's and the period models' to
-- report. A season with some captures (CI's 2026 among them) is judged on every decided
-- matchup, so a period whose captures are missing is found.
--
-- A matchup ESPN has not decided is left out: its lines are still moving.

with covered as (

    select distinct
        seasons.league_id,
        seasons.season
    from {{ ref('int_fantasy__league_seasons') }} as seasons
    inner join {{ ref('stg_espn__matchup_days') }} as days
        on days.league_id = seasons.league_id
        and days.season = seasons.season
    where seasons.platform = 'espn' and seasons.has_rosters

),

played_sides as (

    {%- for side in ['home', 'away'] %}
    select
        league_id,
        season,
        matchup_period,
        matchup_id,
        {{ side }}_team_id as team_id
    from {{ ref('stg_espn__matchups') }}
    where winner != 'UNDECIDED'
    {{ 'union all' if not loop.last }}
    {%- endfor %}

),

sides_with_lines as (

    select distinct
        league_id,
        season,
        matchup_id,
        team_id
    from {{ ref('stg_espn__matchup_player_lines') }}

)

select
    played_sides.league_id,
    played_sides.season,
    played_sides.matchup_period,
    played_sides.matchup_id,
    played_sides.team_id
from played_sides
inner join covered
    on covered.league_id = played_sides.league_id
    and covered.season = played_sides.season
left join sides_with_lines
    on sides_with_lines.league_id = played_sides.league_id
    and sides_with_lines.season = played_sides.season
    and sides_with_lines.matchup_id = played_sides.matchup_id
    and sides_with_lines.team_id = played_sides.team_id
where sides_with_lines.team_id is null
