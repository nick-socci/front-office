{#
  Keep one row per entity, choosing deterministically.

  Raw responses are append-only, so the same game or team appears once per snapshot.
  Deduplication happens at the *entity* grain (game_pk, team_id, ...) rather than per
  request, because a request split into chunks returns overlapping entities and a stale
  copy could otherwise win.

  order_by is a full ORDER BY expression, so callers can add tie-breaks beyond recency.
  That matters more than it sounds: MLB's schedule lists a postponed game and its makeup
  under the SAME game_pk in one response, so recency alone leaves the winner to chance.

  QUALIFY filters on a window function's result; DuckDB and BigQuery both support it.
#}

{% macro fo_latest_by_entity(partition_by, order_by='fetched_at desc') %}
    qualify row_number() over (
        partition by {{ partition_by | join(', ') }}
        order by {{ order_by }}
    ) = 1
{%- endmacro %}
