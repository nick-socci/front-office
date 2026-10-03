-- R6.5 guard: fct_transaction_impact must standardise with the spread the season fact used.
-- It recomputes sd the way it reads it (stddev_pop of value_over_replacement over rows with
-- played_days > 0, per category) and checks, for every season-fact row with a played day
-- and a non-zero sd, that standardised_value * sd equals value_over_replacement within
-- 1e-9. A different sd (say one taken over transactions) would make the two facts' totals
-- incomparable. Returns the rows where it does not.

with category_spread as (

    select
        category_key,
        stddev_pop(value_over_replacement) as standard_deviation
    from {{ ref('fct_player_category_value') }}
    where played_days > 0
    group by category_key

)

select
    facts.platform_player_id,
    facts.fantasy_team_id,
    facts.category_key,
    facts.value_over_replacement,
    facts.standardised_value,
    category_spread.standard_deviation
from {{ ref('fct_player_category_value') }} as facts
inner join category_spread
    on category_spread.category_key = facts.category_key
where facts.played_days > 0
    and category_spread.standard_deviation <> 0
    and abs(facts.standardised_value * category_spread.standard_deviation - facts.value_over_replacement) > 1e-9
