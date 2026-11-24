-- One row per fantasy team per league-season: its name and abbreviation.
--
-- The dimension every team id in the marts points at, so a page can show a team by name
-- and not by number. It is a straight select from int_fantasy__teams: a name belongs to a
-- season (a team can be renamed), so the season is part of the key, and the grain is the
-- seam's. Names are anonymised upstream in CI (fo_anonymize), and the real ones are
-- owners' own, so none is ever committed.
-- dim_fantasy_teams_has_every_team_the_marts_name fails the build on a team id a mart
-- names that has no row here.
{{ config(materialized='table') }}

select
    platform,
    league_id,
    season,
    fantasy_team_id,
    team_name,
    team_abbrev
from {{ ref('int_fantasy__teams') }}
