-- One row per (league, season): the scoring format and where the season stands.

with latest as (

    {{ fo_espn_latest('settings') }}

)

select
    {{ fo_json_text('payload', '$.id') }} as league_id,
    {{ fo_json_int('payload', '$.seasonId') }} as season,
    {{ fo_anonymize(
        fo_json_text('payload', '$.settings.name'),
        "'Private League'"
    ) }} as league_name,
    {{ fo_json_text('payload', '$.settings.scoringSettings.scoringType') }} as scoring_type,
    {{ fo_json_int('payload', '$.settings.size') }} as team_count,
    {{ fo_json_int('payload', '$.settings.scheduleSettings.playoffTeamCount') }} as playoff_team_count,
    {{ fo_json_int('payload', '$.status.currentMatchupPeriod') }} as current_matchup_period,
    {{ fo_json_int('payload', '$.status.latestScoringPeriod') }} as latest_scoring_period,
    {{ fo_json_int('payload', '$.status.finalScoringPeriod') }} as final_scoring_period,
    {{ fo_json_bool('payload', '$.status.isActive') }} as is_active,
    {{ fo_parse_fetched_at() }} as fetched_at
from latest
