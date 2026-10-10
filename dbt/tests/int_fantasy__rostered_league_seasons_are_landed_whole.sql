-- A league-season with roster entries must also have its settings and its matchups.
-- Returns each one that lacks either, with which.
--
-- int_fantasy__league_seasons lets a season be held for its matchup totals alone, and the
-- value models skip a season with no rosters. Catches the opposite, which coverage must
-- not excuse (spec 0085, R2.6): rosters loaded with no settings have no row in that model
-- at all, so every value model would leave the season out without a word; rosters with no
-- matchups would build player values against no matchup at all.

with rostered as (

    select distinct
        league_id,
        season
    from {{ ref('stg_espn__roster_entries') }}

),

with_matchups as (

    select distinct
        league_id,
        season
    from {{ ref('stg_espn__matchups') }}

)

select
    rostered.league_id,
    rostered.season,
    league_seasons.league_id is null as lacks_settings,
    with_matchups.league_id is null as lacks_matchups
from rostered
left join {{ ref('int_fantasy__league_seasons') }} as league_seasons
    on league_seasons.platform = 'espn'
    and league_seasons.league_id = rostered.league_id
    and league_seasons.season = rostered.season
left join with_matchups
    on with_matchups.league_id = rostered.league_id
    and with_matchups.season = rostered.season
where
    league_seasons.league_id is null
    or with_matchups.league_id is null
