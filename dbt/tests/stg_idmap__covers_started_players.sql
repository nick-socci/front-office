-- Each league-season whose started players the SFBB map has no row for, above 5%.
--
-- This guards the map, not the values. The name fallback would resolve 97 to 99.8% of
-- started players even with no map at all, so a test of unresolved players cannot see the
-- map break; that is the job of dim_player_league_seasons_rostered_players_are_resolved.
-- An empty or broken map is 100% here.
--
-- Each league-season is judged on its own players, so loading another season cannot move
-- the test toward failing, and a broken season is not diluted by healthy ones.
--
-- The limit is 5%. The worst real share is 1.87% (9 of 481 started players, 2026). A map
-- frozen a season earlier is put at 7 to 13% by a debut-based proxy (design C8), so 5%
-- sits between the two. The gap that exists comes mostly from map rows with a blank ESPN
-- id: of the 24 players, 15 have an SFBB row with a blank ESPN id, 2 a row under another
-- ESPN id, and 7 no row at all (design C4). Each resolves by name, which marks it
-- player_resolution = 'unambiguous_name'; this test does not warn on them.
--
-- ADR 0089, spec 0177.

{{ config(severity='error') }}

with started_players as (

    select distinct
        entries.league_id,
        entries.season,
        entries.espn_player_id
    from {{ ref('stg_espn__roster_entries') }} as entries
    inner join {{ ref('espn_lineup_slots') }} as slots
        on slots.lineup_slot_id = entries.lineup_slot_id
    where slots.is_starting_slot

),

coverage as (

    -- The CTE is read under another name: BigQuery resolves `started_players.league_id` in
    -- GROUP BY to the count named started_players, not to the CTE.
    select
        started.league_id,
        started.season,
        count(*) as started_players,
        count(case when crosswalk.espn_player_id is null then 1 end) as uncovered_players
    from started_players as started
    left join {{ ref('stg_idmap__players') }} as crosswalk
        on crosswalk.espn_player_id = started.espn_player_id
    group by started.league_id, started.season

)

select
    league_id,
    season,
    started_players,
    uncovered_players
from coverage
where 100 * uncovered_players > 5 * started_players
