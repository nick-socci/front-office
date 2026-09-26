-- One row per fantasy team.
--
-- The source payload also carries `members`, `owners` and `primaryOwner`: real people's
-- names and account GUIDs. None of them are selected here, at any point, by design.

with latest as (

    {{ fo_espn_latest('teams') }}

),

teams as (

    select
        {{ fo_json_text('payload', '$.id') }} as league_id,
        {{ fo_json_int('payload', '$.seasonId') }} as season,
        unnest({{ fo_json_array('payload', '$.teams[*]') }}) as team,
        fetched_at
    from latest

)

select
    teams.league_id,
    teams.season,
    {{ fo_json_int('team', '$.id') }} as team_id,
    {{ fo_anonymize(
        fo_json_text('team', '$.name'),
        "'Team ' || lpad((team ->> '$.id'), 2, '0')"
    ) }} as team_name,
    {{ fo_anonymize(
        fo_json_text('team', '$.abbrev'),
        "'T' || (team ->> '$.id')"
    ) }} as team_abbrev,
    {{ fo_json_int('team', '$.playoffSeed') }} as playoff_seed,
    {{ fo_json_int('team', '$.record.overall.wins') }} as wins,
    {{ fo_json_int('team', '$.record.overall.losses') }} as losses,
    {{ fo_json_int('team', '$.record.overall.ties') }} as ties,
    {{ fo_json_int('team', '$.record.overall.streakLength') }} as streak_length,
    {{ fo_json_text('team', '$.record.overall.streakType') }} as streak_type,
    {{ fo_json_bool('team', '$.eliminated') }} as is_eliminated,
    {{ fo_parse_fetched_at('teams.fetched_at') }} as fetched_at
from teams
