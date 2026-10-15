-- One row per committed matchup-days capture (one scoring period of one league-season)
-- that the loader has listed, parsed as it is read (spec 0150, ADRs 0066 and 0068).
--
-- A payload is up to 1.3 MB: the season's schedule, each matchup carrying both sides'
-- full rosters. stg_espn__matchup_days asks only which matchups attach a roster for the
-- scoring period asked, so a side stays JSON and the model asks it, with fo_json_exists,
-- whether `rosterForCurrentScoringPeriod` is there, exactly as it asked the payload before.
-- `id` is read as text, as the models read the league id.

{% set structure %}
{
  "id": "VARCHAR",
  "seasonId": "BIGINT",
  "schedule": [{
    "matchupPeriodId": "BIGINT",
    "home": "JSON",
    "away": "JSON"
  }]
}
{% endset %}

{{ fo_captures('espn', 'matchup_days', structure) }}
