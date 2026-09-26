-- One row per scored category, in platform-neutral terms.
--
-- A categories league is defined by this list. It is read as data rather than
-- hardcoded because this league scores 17 categories, not a standard 5x5, and the
-- marts have to work for either.
--
-- is_lower_better is the renamed is_reverse: ERA and WHIP are won by the smaller
-- number, and a mart that ranks teams must not assume bigger wins. The name change is
-- deliberate -- "reverse" is ESPN's word for it and means nothing outside ESPN.
--
-- category_key stays the platform's own id, because that is what joins back to the
-- platform's own numbers when reconciling.

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
    stat_id as category_key,
    display_label as category_label,
    stat_abbrev as category_unit,
    is_reverse as is_lower_better
from {{ ref('stg_espn__scoring_categories') }}
