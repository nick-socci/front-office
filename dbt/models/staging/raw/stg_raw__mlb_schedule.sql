-- One row per committed capture of mlb/schedule that the loader has listed, parsed as it
-- is read: `dates`, each day holding its games (spec 0156, ADR 0101; spec 0150, ADR 0068).
--
-- A schedule response is over 1 MB, 20 of them are that large, and every reader of
-- stg_mlb__games reads this view. Read whole, each was a payload value in a query; read
-- through a declared structure only the days and their games are kept, and the rest of the
-- response is dropped while it is read. Each game stays one JSON value, because its readers
-- read it with fo_json_*, from the same paths as before.

{% set structure %}
{"dates": [{"games": ["JSON"]}]}
{% endset %}

{{ fo_captures('mlb', 'schedule', structure) }}
