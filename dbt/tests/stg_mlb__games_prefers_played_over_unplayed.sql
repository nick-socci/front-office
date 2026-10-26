-- A game_pk whose source data contains a played entry must not be represented in the
-- model by a not-played placeholder (postponed or cancelled). Guards the dedupe
-- tie-break in stg_mlb__games: without it, 29 makeup games in 2026 lose to their
-- postponements.

with responses as (

    select dates
    from {{ ref('stg_raw__mlb_schedule') }}

),

days as (

    select schedule_day.games
    from responses
    {{ fo_unnest('responses.dates', 'schedule_day') }}

),

source_games as (

    select game
    from days
    {{ fo_unnest('days.games', 'game') }}

),

played_game_pks as (

    select distinct {{ fo_json_int('source_games.game', '$.gamePk') }} as game_pk
    from source_games
    inner join {{ ref('mlb_game_states') }} as states
        on states.detailed_state = {{ fo_json_text('source_games.game', '$.status.detailedState') }}
    where states.is_played

)

select g.game_pk
from {{ ref('stg_mlb__games') }} as g
inner join played_game_pks as p on p.game_pk = g.game_pk
where not g.is_played
