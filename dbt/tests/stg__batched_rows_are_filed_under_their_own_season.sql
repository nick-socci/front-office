-- Rows of the roster models filed under another season's batch.
--
-- The batched ESPN models are built a season at a time (spec 0143): dbt runs each once per
-- calendar year and replaces that year's rows, on the column season_start, which comes from
-- the `partitions` the loader stored. Their `season` column comes from the payload itself.
-- A row whose season_start is not the first of January of its own season was read from a
-- capture filed under one season holding another's data. It would be replaced, or kept,
-- with the wrong batch.
--
-- The MLB game logs are not here: a boxscore carries no season of its own to compare with.

with rows_of_the_batched as (

    select
        'stg_espn__roster_entries' as model,
        season,
        season_start
    from {{ ref('stg_espn__roster_entries') }}

    union all

    select
        'stg_espn__roster_entry_slots' as model,
        season,
        season_start
    from {{ ref('stg_espn__roster_entry_slots') }}

    union all

    select
        'stg_espn__player_game_stats' as model,
        season,
        season_start
    from {{ ref('stg_espn__player_game_stats') }}

    union all

    select
        'stg_espn__matchup_days' as model,
        season,
        season_start
    from {{ ref('stg_espn__matchup_days') }}

)

select
    model,
    season,
    season_start,
    count(*) as row_count
from rows_of_the_batched
where season_start is distinct from {{ fo_year_start('season') }}
group by model, season, season_start
