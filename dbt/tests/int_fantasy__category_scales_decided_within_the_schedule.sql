{{ config(severity='warn') }}

-- A category whose scale uses history has decided no more regular-season matchups than the
-- settings schedule holds. Returns each one that has, with both counts.
--
-- More matchups decided than scheduled means M is stale: the schedule was extended after the
-- newest settings capture. The weight is already clamped at 0 there, so the scale is the
-- season's own and nothing is wrong with the value. It warns, not fails, so a stale M is
-- seen without stopping a build.
--
-- Only categories that use history: a current_season scale counts every matchup, playoffs
-- included (ADR 0010), so its count is not comparable with M.
--
-- Catches: an extended schedule going unseen (spec 0161, R1.9).

select
    platform,
    league_id,
    season,
    category_key,
    matchups_measured,
    scheduled_matchups
from {{ ref('int_fantasy__category_scales') }}
where
    scale_source = 'prior_and_current_seasons'
    and scheduled_matchups is not null
    and matchups_measured > scheduled_matchups
