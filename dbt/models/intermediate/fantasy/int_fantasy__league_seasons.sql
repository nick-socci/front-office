-- One row per league-season this project holds, and whether its rosters are loaded.
--
-- A league-season need not be landed whole. A past season can be landed for its matchup
-- totals alone (settings, matchups and the two schedules, spec 0085): the platform's own
-- numbers are all there, and nothing we could compute a value from is. has_rosters is how
-- the rest of the build tells the two apart (ADR 0026):
--
--   a model or test that needs rosters applies where has_rosters is true;
--   one that describes what the platform reported applies to every row here.
--
-- Coverage is read from what is loaded, never declared in a seed or a variable, so it
-- cannot disagree with the data, and a season whose rosters are landed later becomes
-- covered with no change here.
--
-- The spine is the settings: a league-season exists for this project once its settings are
-- loaded. Rosters loaded with no settings would therefore have no row, and be quietly
-- left out of everything; int_fantasy__rostered_league_seasons_are_landed_whole fails the
-- build on that instead. Coverage describes a season deliberately landed in part, not one
-- half landed by accident.
--
-- One boolean on purpose. A season with rosters and a missing boxscore is covered, and is
-- reported by the input checks on int_fantasy__started_player_days (#25), not here.
--
-- A table despite being tiny, like int_fantasy__categories: a contract's not_null
-- constraints are dropped on a view.
{{ config(materialized='table') }}

with rostered as (

    select distinct league_id, season
    from {{ ref('stg_espn__roster_entries') }}

)

select
    'espn' as platform,
    settings.league_id,
    settings.season,
    rostered.league_id is not null as has_rosters
from {{ ref('stg_espn__league_settings') }} as settings
left join rostered
    on rostered.league_id = settings.league_id
    and rostered.season = settings.season
