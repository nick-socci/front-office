-- One row per scored category of every league-season loaded: the scale the league
-- host's own reported margins give for that season alone, and how many matchups are
-- behind it.
--
-- This is the report of how one season compares with another, and of how much was
-- loaded. Nothing downstream computes a value from it: the scale a league-season's
-- values divide by is int_fantasy__category_scales, which blends the earlier seasons
-- with the season so far (ADR 0027) and reads the margins directly.
--
-- matchups_measured is on every row, and is the point of the model (owner, #57). A
-- season that was not played and a matchups capture that parsed to nothing look the same
-- in staging, a league-season with settings and no matchups, and nothing in dbt fails on
-- either. Here it is 18 rows of zero for 2020, where it can be seen.
--
-- The spine is the category list, left-joined, so a category or a season with nothing to
-- measure is a row and not an absence.
--
-- Only rows with is_measured count: regular-season matchups, and for a rate those where
-- both sides' denominators are reported and above zero. So a rate's scale and its
-- side_denominator come from the same matchups, and a rate the host reports no
-- denominator for has matchups_measured 0 (AVG in 2018: ESPN reports no at-bats).
--
-- Both numbers describe a matchup period of usual volume: the scale is measured from
-- standard_margin, and a side's denominator is divided by its period's relative volume.
--
-- margin_scale is a root mean square about zero, as ADR 0010 has it, summed in matchup
-- order: the last digit of a floating-point sum depends on the order of its terms, and
-- row order changes from build to build (spec 0028, R4.13).

{{ config(materialized='table') }}

with measured as (

    select
        platform,
        league_id,
        season,
        category_key,
        count(*) as matchups_measured,
        sqrt(sum(standard_margin * standard_margin order by matchup_id) / count(*)) as margin_scale,
        sum((home_denominator + away_denominator) / relative_volume order by matchup_id)
            / (2 * count(*)) as side_denominator
    from {{ ref('int_fantasy__reported_matchup_margins') }}
    where is_measured
    group by platform, league_id, season, category_key

)

select
    categories.platform,
    categories.league_id,
    categories.season,
    categories.category_key,
    coalesce(measured.matchups_measured, 0) as matchups_measured,
    measured.margin_scale,
    measured.side_denominator
from {{ ref('int_fantasy__categories') }} as categories
left join measured
    on measured.platform = categories.platform
    and measured.league_id = categories.league_id
    and measured.season = categories.season
    and measured.category_key = categories.category_key
