-- One row per fantasy team, in platform-neutral terms.
--
-- Part of the seam. Every model above this layer reads int_fantasy__*, never
-- stg_espn__*, so adding Yahoo or Sleeper means writing a second set of staging models
-- and a second branch here -- not touching a single mart.
--
-- The contract in the schema file is what makes that a guarantee rather than a claim:
-- a second platform that produces the wrong column type fails the build.

-- Materialized as a table despite being tiny. A contract's not_null constraints are
-- silently dropped on a view -- dbt warns "Constraint types are not supported for view
-- materializations" and builds it anyway -- so a view here would enforce column names
-- and types while quietly abandoning the rest. Twelve rows is not worth a half-kept
-- promise.
{{ config(materialized='table') }}

select
    'espn' as platform,
    league_id,
    season,
    team_id as fantasy_team_id,
    team_name,
    team_abbrev,
    playoff_seed,
    wins,
    losses,
    ties
from {{ ref('stg_espn__teams') }}
