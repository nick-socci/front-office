-- One row per (season, MLB player): MLB's season player list, as the newest capture of
-- that season that lists him describes him.
--
-- Why it exists: the player dimension is keyed by MLB's id, and MLB's own list is the
-- source of a player's name and attributes (spec 0060). The list is a snapshot endpoint,
-- fetched on every MLB run, so many captures describe one season. A player a later
-- capture no longer lists keeps his last row, which is why the dedupe is per player and
-- not "take the newest capture".
--
-- `season` comes from the capture's request, not the payload: the payload has no season
-- field. Of the name fields only `fullName` is read; MLB's other name parts are not
-- needed and not kept.
--
-- `primary_position` is MLB's designation as of the fetch (P, SS, TWP, ...), not on a
-- date in the season, like ESPN's eligibility.
--
-- The payload is projected away in `header` before the unnest (AGENTS.md rule 1): the
-- SELECT that unnests carries only `season` and `fetched_at` beside the people.

with responses as (

    select
        payload,
        request_key,
        fetched_at
    from {{ source('raw', 'api_responses') }}
    where source = 'mlb'
      and endpoint = 'players'

),

header as (

    select
        {{ fo_request_param('request_key', 'season') }} as season,
        fetched_at,
        {{ fo_json_array('payload', '$.people[*]') }} as people
    from responses

),

listed as (

    select
        season,
        fetched_at,
        unnest(people) as person
    from header

)

select
    season,
    {{ fo_json_int('person', '$.id') }} as mlbam_player_id,
    {{ fo_json_text('person', '$.fullName') }} as player_name,
    {{ fo_json_text('person', '$.primaryPosition.abbreviation') }} as primary_position,
    {{ fo_json_text('person', '$.batSide.code') }} as bats,
    {{ fo_json_text('person', '$.pitchHand.code') }} as throws,
    {{ fo_json_date('person', '$.birthDate') }} as birth_date,
    {{ fo_json_date('person', '$.mlbDebutDate') }} as mlb_debut_date,
    {{ fo_parse_fetched_at() }} as fetched_at
from listed
{{ fo_latest_by_entity(['season', fo_json_string('person', '$.id') | trim], 'fetched_at desc') }}
