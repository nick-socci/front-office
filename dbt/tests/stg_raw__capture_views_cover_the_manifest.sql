-- Every capture the manifest lists is a row of its endpoint's capture view, once.
--
-- A capture view keeps the files its glob reads that the manifest lists (ADR 0067). A
-- listed capture whose file the glob does not match (a stamp without its Z, a directory
-- moved after the load) would vanish from every model with no error; a file matched twice
-- would double it. This compares, per endpoint, the manifest's count with the view's.
--
-- The one reader of raw.captures outside the capture views, named so by
-- ingestion/tests/test_dbt_json_rule.py, because what it checks is the views against it.

with manifest as (

    select source, endpoint, count(*) as listed
    from {{ source('raw', 'captures') }}
    group by source, endpoint

),

viewed as (

    {% for source_name, endpoint in [
        ('espn', 'roster'), ('espn', 'matchup_days'), ('mlb', 'boxscore'),
        ('espn', 'settings'), ('espn', 'teams'), ('espn', 'matchups'),
        ('espn', 'pro_schedule'), ('espn', 'transactions'), ('mlb', 'schedule'),
        ('mlb', 'players'), ('idmap', 'player_id_map')
    ] %}
    select '{{ source_name }}' as source, '{{ endpoint }}' as endpoint, count(*) as viewed
    from {{ ref('stg_raw__' ~ source_name ~ '_' ~ endpoint) }}
    {{ 'union all' if not loop.last }}
    {% endfor %}

)

select
    coalesce(manifest.source, viewed.source) as source,
    coalesce(manifest.endpoint, viewed.endpoint) as endpoint,
    coalesce(manifest.listed, 0) as listed,
    coalesce(viewed.viewed, 0) as viewed
from manifest
full outer join viewed
    on viewed.source = manifest.source and viewed.endpoint = manifest.endpoint
where coalesce(manifest.listed, 0) != coalesce(viewed.viewed, 0)
