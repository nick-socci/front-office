-- One row per committed matchup-days capture (one scoring period of one league-season)
-- that the loader has listed, parsed as it is read (spec 0150, ADRs 0066 and 0068).
--
-- A payload is up to 1.3 MB: the season's schedule, each matchup carrying both sides'
-- full rosters, and `teams` and `settings`, which carry member data. Parsed from the
-- file with this structure, everything not declared is dropped while reading; no name,
-- no `lineupSlotId` (0 on every entry) and nothing of `teams` or `settings` is a field
-- of this view (spec 0147, R1.4).
--
-- The structure is the union of what its readers take:
--   * `id` (the league, read as text, as the models read the league id), `seasonId` and
--     `scoringPeriodId` (the period ESPN says it answered, which
--     stg_espn__matchup_days_answer_the_period_asked compares with the one asked for).
--   * per matchup: `id` (the matchup's id) and `matchupPeriodId`.
--   * per side (`home`, `away`): `teamId`; `rosterForCurrentScoringPeriod`, kept JSON
--     because stg_espn__matchup_days reads only whether it is there (ADR 0055: ESPN
--     marks the matchups of the period the day belongs to) and the roster inside it is
--     never selected; and `rosterForMatchupPeriod.entries[]`, ESPN's own record of what
--     each player was credited with in the matchup, which stg_espn__matchup_player_lines
--     reads: the entry's `playerId` and its stat lines' `statSourceId`,
--     `statSplitTypeId`, `scoringPeriodId` and `stats` (a map from stat id to its
--     value as JSON: that model unnests its entries with fo_map_entries, since unnesting
--     keys beside values as a subquery made DuckDB hold every parsed capture, spec 0156).
-- A side with none of these keys (a playoff bye has an empty `away`) is a struct of
-- nulls. A field a model reads that is not declared here fails that model when it is
-- compiled.

{% set structure %}
{
  "id": "VARCHAR",
  "seasonId": "BIGINT",
  "scoringPeriodId": "BIGINT",
  "schedule": [{
    "id": "BIGINT",
    "matchupPeriodId": "BIGINT",
    "home": {
      "teamId": "BIGINT",
      "rosterForCurrentScoringPeriod": "JSON",
      "rosterForMatchupPeriod": {"entries": [{
        "playerId": "BIGINT",
        "playerPoolEntry": {"player": {"stats": [{
          "statSourceId": "BIGINT",
          "statSplitTypeId": "BIGINT",
          "scoringPeriodId": "BIGINT",
          "stats": {"__map__": "JSON"}
        }]}}
      }]}
    },
    "away": {
      "teamId": "BIGINT",
      "rosterForCurrentScoringPeriod": "JSON",
      "rosterForMatchupPeriod": {"entries": [{
        "playerId": "BIGINT",
        "playerPoolEntry": {"player": {"stats": [{
          "statSourceId": "BIGINT",
          "statSplitTypeId": "BIGINT",
          "scoringPeriodId": "BIGINT",
          "stats": {"__map__": "JSON"}
        }]}}
      }]}
    }
  }]
}
{% endset %}

{{ fo_captures('espn', 'matchup_days', structure) }}
