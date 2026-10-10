-- Fails when the totals path of int_fantasy__lineup_category_totals does not reproduce the
-- scored totals (R5.3): a credited component the totals path gets wrong, in the model's own
-- statements.
--
-- The optimal rows come through the same statements as the actual rows, so the actual rows
-- are the one place the path can be proved against something it did not compute:
-- fct_matchup_category_scores.team_value, built from int_fantasy__matchup_side_totals and
-- reconciled with ESPN. The comparison is exact (is distinct from; no tolerance, no
-- rounding), both ways: a side and category of the fact with no actual row, a value that
-- differs, and an actual row the fact does not have. A row comes back for each.

with fact as (

    select
        platform,
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        category_key,
        team_value
    from {{ ref('fct_matchup_category_scores') }}

),

actual as (

    select
        platform,
        league_id,
        season,
        matchup_id,
        fantasy_team_id,
        category_key,
        category_value
    from {{ ref('int_fantasy__lineup_category_totals') }}
    where lineup = 'actual'

)

select
    coalesce(fact.platform, actual.platform) as platform,
    coalesce(fact.league_id, actual.league_id) as league_id,
    coalesce(fact.season, actual.season) as season,
    coalesce(fact.matchup_id, actual.matchup_id) as matchup_id,
    coalesce(fact.fantasy_team_id, actual.fantasy_team_id) as fantasy_team_id,
    coalesce(fact.category_key, actual.category_key) as category_key,
    fact.team_value,
    actual.category_value,
    (fact.category_key is null) as fact_has_no_row,
    (actual.category_key is null) as totals_have_no_actual_row
from fact
full outer join actual
    on actual.platform = fact.platform
    and actual.league_id = fact.league_id
    and actual.season = fact.season
    and actual.matchup_id = fact.matchup_id
    and actual.fantasy_team_id = fact.fantasy_team_id
    and actual.category_key = fact.category_key
where
    fact.category_key is null
    or actual.category_key is null
    or actual.category_value is distinct from fact.team_value
