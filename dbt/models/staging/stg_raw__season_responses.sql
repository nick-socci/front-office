{{ config(event_time='season_start') }}

{#
  The raw responses, with the season a capture belongs to as a date.

  Models that parse one large payload per game or per scoring period are built a season
  at a time (dbt microbatch, one batch per calendar year). dbt filters each batch on the
  event time of the relation it reads, and the raw table holds a capture's season only
  inside `partitions`, so this view exposes it as a date: the first of January of the
  season.

  A capture with no season (the id map's partitions are empty) has a null season_start,
  so it falls in no batch.

  A view, so it costs nothing until a model reads it (spec 0143, ADR 0058).
#}

select
    source,
    endpoint,
    request_path,
    request_key,
    fetched_at,
    partitions,
    payload,
    file_path,
    {{ fo_year_start(fo_json_int('partitions', '$.season')) }} as season_start
from {{ source('raw', 'api_responses') }}
