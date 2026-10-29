{#
  The newest landed ESPN response for one endpoint, one per league and season.

  Settings, teams, matchups and rosters are snapshot endpoints, so the raw table holds
  every version ever fetched. Staging wants the latest of each league-season (and of each
  scoring period, for rosters), which is what this filters to. Selecting the latest
  globally would let whichever league was fetched last hide every other league.

  league_id (text) and season (integer) come from the `partitions` the loader stored, not
  from the payload: they are the identity the capture was filed under. A singular test
  checks that the payload agrees.

  file_path is unique per capture and is the deterministic tie-break (rule 5). (#28 once
  joined payloads back to ranked keys and ran out of memory: the join kept every payload
  on its build side. Here the build side is the manifest's paths, and no payload is a
  value at all.)

  The rows come from the endpoint's capture view (spec 0150), and which capture is the
  newest is decided on the manifest's columns alone, never by ranking the view's parsed
  rows: a window holds every row it ranks, and the parsed rosters of eight seasons ran
  DuckDB out of memory at 2 GB where this form needs 0.18 GB (spec 0150, R3.6, C19). The
  view's rows are kept by a semi-join on file_path, which streams.
#}

{#
  The manifest's file_path of the newest capture of each league and season (and of each
  value of `extra_partition`, a request parameter), as a query of one column. fo_espn_latest
  keeps the view's rows with it; a model that needs only the narrow columns of those
  captures reads the manifest with it and leaves the parsed rows to a single reader, since
  DuckDB materializes parsed captures read twice (spec 0156, C11).
#}
{% macro fo_espn_latest_paths(endpoint, extra_partition=none) %}

    {%- set partition_by = [
        fo_json_text('keys.partitions', '$.league_id'),
        fo_json_int('keys.partitions', '$.season'),
    ] -%}
    {%- if extra_partition -%}
        {%- do partition_by.append(fo_request_param('keys.request_key', extra_partition)) -%}
    {%- endif %}

    select keys.file_path
    from {{ fo_capture_keys() }} as keys
    where keys.source = 'espn'
      and keys.endpoint = '{{ endpoint }}'
    {{ fo_keep_first(partition_by, 'keys.fetched_at desc, keys.file_path desc') }}

{%- endmacro %}

{% macro fo_espn_latest(endpoint, extra_partition=none) %}

    select
        captures.*,
        {{ fo_json_text('captures.partitions', '$.league_id') }} as league_id,
        cast({{ fo_json_int('captures.partitions', '$.season') }} as integer) as season
    from {{ ref('stg_raw__espn_' ~ endpoint) }} as captures
    where captures.file_path in (
        {{ fo_espn_latest_paths(endpoint, extra_partition) }}
    )

{%- endmacro %}
