-- A season with captures of a batched model's endpoint, and no row of it in the model.
--
-- The five models are built a season at a time (spec 0143): dbt runs one batch per
-- calendar year, from `first_season_start` to the year of the run, and no further. A
-- capture filed under a later season is in no batch, and one filed under an earlier season
-- than `first_season_start` is in none either: its rows would vanish with no error. This
-- test makes that loss loud. It returns one row per (model, season_start) where the
-- endpoint has a capture with a season and the model holds no row of that season_start.
--
-- When it fails: for a season later than the run's year, run the build with
-- `--event-time-start` and `--event-time-end` covering the season (the end is exclusive:
-- the first of January of the year after). For a season earlier than the first batch,
-- lower `first_season_start` in dbt_project.yml to its first of January and run the build
-- with `--full-refresh`.
--
-- Reads source, endpoint and season_start of the view only, never the payload. Decided by
-- the owner on 2026-10-12.

with endpoints as (

    select
        'stg_espn__roster_entries' as model,
        'espn' as source,
        'roster' as endpoint

    union all

    select
        'stg_espn__roster_entry_slots' as model,
        'espn' as source,
        'roster' as endpoint

    union all

    select
        'stg_espn__player_game_stats' as model,
        'espn' as source,
        'roster' as endpoint

    union all

    select
        'stg_mlb__batting_game_logs' as model,
        'mlb' as source,
        'boxscore' as endpoint

    union all

    select
        'stg_mlb__pitching_game_logs' as model,
        'mlb' as source,
        'boxscore' as endpoint

),

captured as (

    select distinct
        endpoints.model,
        responses.season_start
    from {{ ref('stg_raw__season_responses') }} as responses
    inner join endpoints
        on endpoints.source = responses.source
        and endpoints.endpoint = responses.endpoint
    where responses.season_start is not null

),

held as (

    select
        'stg_espn__roster_entries' as model,
        season_start
    from {{ ref('stg_espn__roster_entries') }}
    group by season_start

    union all

    select
        'stg_espn__roster_entry_slots' as model,
        season_start
    from {{ ref('stg_espn__roster_entry_slots') }}
    group by season_start

    union all

    select
        'stg_espn__player_game_stats' as model,
        season_start
    from {{ ref('stg_espn__player_game_stats') }}
    group by season_start

    union all

    select
        'stg_mlb__batting_game_logs' as model,
        season_start
    from {{ ref('stg_mlb__batting_game_logs') }}
    group by season_start

    union all

    select
        'stg_mlb__pitching_game_logs' as model,
        season_start
    from {{ ref('stg_mlb__pitching_game_logs') }}
    group by season_start

)

select
    captured.model,
    captured.season_start
from captured
left join held
    on held.model = captured.model
    and held.season_start = captured.season_start
where held.season_start is null
