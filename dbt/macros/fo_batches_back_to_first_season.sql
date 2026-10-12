{#
  How many batches before the current one an ordinary run of a batched model redoes.

  That is dbt's "lookback". The models built a season at a time (dbt microbatch, one
  batch per calendar year) want every build to redo every season, so the table is what a
  build in one piece would give (ADR 0059). This is the number of years from the year of
  var('first_season_start') to the year of the run, so the lookback reaches exactly the
  first season and no batch from before it is run. It is computed, not a constant, for
  that reason: a fixed 20 would run empty batches back to 2006.

  An integer. A table on BigQuery ignores it (spec 0143, ADR 0060).
#}

{% macro fo_batches_back_to_first_season() %}
    {{- return(run_started_at.year - (var('first_season_start')[:4] | int)) -}}
{% endmacro %}
