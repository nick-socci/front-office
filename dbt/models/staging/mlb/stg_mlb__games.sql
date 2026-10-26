-- One row per MLB regular-season game.
--
-- The schedule is a snapshot endpoint: games get postponed, resumed and rescheduled,
-- so several fetches describe the same game_pk. We keep the newest.
--
-- One MLB quirk drives the dedupe tie-break: a postponed game and the makeup game that
-- replaced it share a game_pk and both appear in a single response, both with
-- abstractGameState = 'Final'. Recency cannot separate them (same fetched_at), so
-- played games are preferred over not-played placeholders explicitly. In the 2026 season
-- this affects 29 postponed games. A cancelled entry is demoted the same way: "not
-- played" means the seed's is_played = false, the same set as ingestion's NOT_PLAYED,
-- so the two pick the same row. A state the seed doesn't list ranks with the played
-- ones, as in ingestion, and then fails the build on its own.
--
-- Two entries can still tie: a suspended game has its original and its resumed entry, both
-- 'Final', and a game postponed and then cancelled has both, neither played. 42 games of
-- 2018 to 2026 do. The entry with the latest scheduled start wins, the one where the game
-- ended (the owner, 2026-10-11; ADR 0020 reads a game by its last scheduled start too).
-- gameDate is an ISO instant in UTC, so its text sorts as time. Without this the row kept
-- was whichever the warehouse met first, and DuckDB and BigQuery met different ones (spec
-- 0130).

with responses as (

    select
        dates,
        fetched_at
    from {{ ref('stg_raw__mlb_schedule') }}

),

days as (

    -- One row per day of each response. The days are unnested straight from `responses`,
    -- which holds only `dates` and the stamp (AGENTS.md rule 1): an unnest repeats every
    -- other column of its relation once per element.
    select
        responses.fetched_at,
        schedule_day.games
    from responses
    {{ fo_unnest('responses.dates', 'schedule_day') }}

),

games as (

    -- One row per game: a day's list of games, taken as a column first so that nothing
    -- large sits beside this unnest either.
    select
        days.fetched_at,
        game
    from days
    {{ fo_unnest('days.games', 'game') }}

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
    -- Whether the game was actually played, from the mlb_game_states seed. Null for a
    -- state the seed doesn't list, which fails the build: a new MLB state has to be
    -- classified by hand, not defaulted either way.
    states.is_played,
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
left join {{ ref('mlb_game_states') }} as states
    on states.detailed_state = {{ fo_json_text('game', '$.status.detailedState') }}
where {{ fo_json_text('game', '$.gameType') }} = 'R'
{{ fo_latest_by_entity(
    ['game_pk'],
    order_by="fetched_at desc, case when states.is_played = false then 1 else 0 end, "
    ~ fo_json_text('game', '$.gameDate') ~ " desc"
) }}
