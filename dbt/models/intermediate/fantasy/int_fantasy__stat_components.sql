-- How every platform stat is computed from credited components: one row per (stat,
-- part, component).
--
-- This is what makes the scoring rules-driven rather than hardcoded. A stat's value for
-- a matchup side is
--
--     sum(weight * component) over its numerator rows
--   / sum(weight * component) over its denominator rows      (if it has any)
--
-- so a count is one numerator row (HR = home_runs), a sum is several (SVHD = saves +
-- holds), and a rate puts its scale in the weights (ERA = 27 * earned_runs /
-- outs_recorded, WHIP = (3 * hits_allowed + 3 * pitcher_walks) / outs_recorded, since
-- ESPN keeps innings as outs). A league scoring different categories, or a platform
-- with different stat ids, changes the seed, not the SQL.
--
-- The rows cover every stat ESPN reports for a matchup side, not only the scored
-- categories: the extra ones (AB, ER, SV...) are the components behind the ratios, and
-- covering them lets the reconciliation check components and rates separately.
--
-- Component names are columns of int_fantasy__started_player_days, so a typo would
-- silently score zero; the accepted_values test on component prevents that.

{{ config(materialized='table') }}

select
    'espn' as platform,
    stat_id as stat_key,
    part,
    component,
    weight
from {{ ref('espn_stat_components') }}
