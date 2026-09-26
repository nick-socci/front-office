-- One row per MLB regular-season game.
--
-- The schedule is a snapshot endpoint: games get postponed, resumed and rescheduled,
-- so several fetches describe the same game_pk. We keep the newest.
--
-- One MLB quirk drives the dedupe tie-break: a postponed game and the makeup game that
-- replaced it share a game_pk and both appear in a single response, both with
-- abstractGameState = 'Final'. Recency cannot separate them (same fetched_at), so
-- played games are preferred over postponed placeholders explicitly. In the 2026 season
-- this affects 29 games.

with responses as (

    select
        payload,
        fetched_at
    from {{ source('raw', 'api_responses') }}
    where source = 'mlb'
      and endpoint = 'schedule'

),

games as (

    select
        fetched_at,
        unnest({{ fo_json_array('payload', '$.dates[*].games[*]') }}) as game
    from responses

)

select
    {{ fo_json_int('game', '$.gamePk') }} as game_pk,
    {{ fo_json_text('game', '$.gameGuid') }} as game_guid,
    {{ fo_json_text('game', '$.gameType') }} as game_type,
    {{ fo_json_int('game', '$.season') }} as season,
    {{ fo_json_date('game', '$.officialDate') }} as official_date,
    {{ fo_json_timestamp('game', '$.gameDate') }} as game_start_at_utc,
    {{ fo_json_text('game', '$.status.abstractGameState') }} as game_state,
    {{ fo_json_text('game', '$.status.detailedState') }} as game_state_detail,
    {{ fo_json_text('game', '$.status.detailedState') }} = 'Postponed' as is_postponed,
    {{ fo_json_int('game', '$.teams.home.team.id') }} as home_team_id,
    {{ fo_json_text('game', '$.teams.home.team.name') }} as home_team_name,
    {{ fo_json_int('game', '$.teams.away.team.id') }} as away_team_id,
    {{ fo_json_text('game', '$.teams.away.team.name') }} as away_team_name,
    {{ fo_json_int('game', '$.teams.home.score') }} as home_score,
    {{ fo_json_int('game', '$.teams.away.score') }} as away_score,
    {{ fo_json_int('game', '$.venue.id') }} as venue_id,
    {{ fo_json_text('game', '$.venue.name') }} as venue_name,
    {{ fo_json_text('game', '$.dayNight') }} as day_night,
    {{ fo_json_int('game', '$.gameNumber') }} as game_number,
    -- MLB sends "N" / "Y" (split) / "S" (same-day), not a boolean.
    {{ fo_json_text('game', '$.doubleHeader') }} as doubleheader_code,
    {{ fo_json_bool('game', '$.teams.home.isWinner') }} as home_is_winner,
    -- Present only for affected games; a suspended game can span two dates.
    {{ fo_json_timestamp('game', '$.rescheduledFrom') }} as rescheduled_from,
    {{ fo_json_timestamp('game', '$.resumedFrom') }} as resumed_from,
    {{ fo_parse_fetched_at() }} as fetched_at
from games
where {{ fo_json_text('game', '$.gameType') }} = 'R'
{{ fo_latest_by_entity(
    ['game_pk'],
    order_by="fetched_at desc, case when game ->> '$.status.detailedState' = 'Postponed' then 1 else 0 end"
) }}
