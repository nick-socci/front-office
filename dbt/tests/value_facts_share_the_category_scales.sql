-- Guard that fct_player_category_value is on the scales of int_fantasy__category_scales
-- (ADR 0010). For every row with a played day, a value over replacement, and a usable scale
-- (a non-null, non-zero margin_scale, and for a rate a non-null, non-zero side_denominator),
-- scaled_value * margin_scale * side_denominator must give back value_over_replacement
-- within 1e-9. A count has a null side_denominator, so coalesce makes it 1. Together with
-- fct_transaction_impact_an_add_covering_a_pair_reproduces_the_season_fact, which holds the
-- transaction fact to the season fact, this ties the transaction fact to the same scale.
-- A rate is recognised by the fact's denominator, which is null only for a count. Returns
-- the rows where it does not.

select
    facts.platform_player_id,
    facts.fantasy_team_id,
    facts.category_key,
    facts.value_over_replacement,
    facts.scaled_value,
    scales.margin_scale,
    scales.side_denominator
from {{ ref('fct_player_category_value') }} as facts
inner join {{ ref('int_fantasy__category_scales') }} as scales
    on scales.platform = facts.platform
    and scales.league_id = facts.league_id
    and scales.season = facts.season
    and scales.category_key = facts.category_key
where facts.played_days > 0
    and facts.value_over_replacement is not null
    and coalesce(scales.margin_scale, 0) <> 0
    and (facts.denominator is null or coalesce(scales.side_denominator, 0) <> 0)
    -- A null scaled_value here is a failure too: with a played day, a value and a usable
    -- scale it must be a number, and a comparison against null would silently pass.
    and (
        facts.scaled_value is null
        or abs(
            facts.scaled_value * scales.margin_scale * coalesce(scales.side_denominator, 1)
            - facts.value_over_replacement
        ) > 1e-9
    )
