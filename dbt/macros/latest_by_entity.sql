{#
  Rankings that stop the build on a tie where they cut.

  Raw responses are append-only, so the same game or team appears once per snapshot, and
  deduplication happens at the *entity* grain (game_pk, team_id, ...) rather than per
  request: a request split into chunks returns overlapping entities and a stale copy could
  otherwise win. order_by is a full ORDER BY expression, so callers add tie-breaks beyond
  recency. MLB's schedule lists a postponed game and its makeup under the SAME game_pk in
  one response, so recency alone leaves the winner to chance.

  A tie is the failure that looks like success. When two rows share every order_by value
  at the cut, row_number() still returns one of them, DuckDB and BigQuery pick differently,
  and nothing says so. So each ranking checks its own order on the rows it ranks, in every
  build (ADR 0107): over the window it ranks by, the row in place n + 1 is compared with
  place n through rank(), and when they tie the CASE branch calls error(), which stops the
  statement with the node, the place and the partition's key values. The fixtures hold no
  tie, so the check costs nothing there and fires only on data that has one. rank() and
  row_number() over one window share a single sort. A tie below the cut, or one inside the
  kept rows, changes nothing and passes.

  Every window whose result depends on row order goes through fo_keep_first (keep n rows) or
  fo_row_number (number every row), held by a text rule (ADR 0108). fo_latest_by_entity is
  fo_keep_first with n = 1 and its callers' signature.

  error(string) is the same call in DuckDB and BigQuery, so there is no dispatch and one
  SQL text serves both. The window is written out each time, not named: a model's own
  WINDOW clause would collide, and identical windows are merged anyway. QUALIFY filters on
  a window function's result; both warehouses support it.
#}


{# The window ranked over: `(partition by ... order by ...)`, or no partition clause. #}
{% macro fo_tie_window(partition_by, order_by) -%}
    ({% if partition_by %}partition by {{ partition_by | join(', ') }} {% endif %}order by {{ order_by }})
{%- endmacro %}


{#
  The error text: `<node>: <what> in (<partition key values>)`. The keys are ids (league,
  season, game, player), never names. A null key reads as `null`; no partition reads as
  `whole input`. The node is `this.identifier` (`inline_query` under `dbt show --inline`),
  or `inline` where `this` is undefined.
#}
{% macro fo_tie_message(partition_by, place, what='rows tie for place ') -%}
    {%- set node = this.identifier if this is defined else 'inline' -%}
    {%- set keys = [] -%}
    {%- for key in partition_by -%}
        {%- do keys.append("coalesce(cast(" ~ key ~ " as " ~ fo_type_text() ~ "), 'null')") -%}
    {%- endfor -%}
    {%- set keyed = keys | join(", ', ', ") if keys else "'whole input'" -%}
    {%- if what == 'rows tie for place ' -%}
        concat('{{ node }}: rows tie for place ', cast({{ place }} as {{ fo_type_text() }}), ' in (', {{ keyed }}, ')')
    {%- else -%}
        concat('{{ node }}: {{ what }} in (', {{ keyed }}, ')')
    {%- endif -%}
{%- endmacro %}


{#
  Keep places 1 to `rows` of each partition. `rows` is an integer, or a column expression
  with one value in each partition: with several values there is no single cut, and a tie
  could pass unseen, so that stops the build too.
#}
{% macro fo_keep_first(partition_by, order_by, rows=1) %}
    {%- set over = fo_tie_window(partition_by, order_by) -%}
    {%- set literal = rows is integer or (rows | string).isdigit() -%}
    qualify case
        when row_number() over {{ over }} = ({{ rows }}) + 1
            and rank() over {{ over }} <= ({{ rows }})
            then error({{ fo_tie_message(partition_by, '(' ~ rows ~ ')') }})
        {%- if not literal %}
        when min({{ rows }}) over ({% if partition_by %}partition by {{ partition_by | join(', ') }}{% endif %})
            <> max({{ rows }}) over ({% if partition_by %}partition by {{ partition_by | join(', ') }}{% endif %})
            then error({{ fo_tie_message(partition_by, none, 'the number of rows to keep differs') }})
        {%- endif %}
        else row_number() over {{ over }} <= ({{ rows }})
    end
{%- endmacro %}


{# Number every row of each partition from 1; any tie in the partition stops the build. #}
{% macro fo_row_number(partition_by, order_by) -%}
    {%- set over = fo_tie_window(partition_by, order_by) -%}
    case
        when rank() over {{ over }} <> row_number() over {{ over }}
            then error({{ fo_tie_message(partition_by, 'rank() over ' ~ over) }})
        else row_number() over {{ over }}
    end
{%- endmacro %}


{% macro fo_latest_by_entity(partition_by, order_by='fetched_at desc') %}
    {{ fo_keep_first(partition_by, order_by, 1) }}
{%- endmacro %}
