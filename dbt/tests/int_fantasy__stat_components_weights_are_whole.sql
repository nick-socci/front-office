-- Every weight in int_fantasy__stat_components is a whole number of at most 10^6 in
-- magnitude. Returns each row whose weight is not, with its platform, stat_key, part and
-- component.
--
-- rec_fantasy__category_wins_added sums weight * swapped_total three times without an
-- `order by` (an `order-exempt:` claim, ADR 0046). Those sums are exact in any order only
-- while every term is a whole number and their magnitudes sum below 2^53. Swapped totals
-- are whole counts of one matchup period, in the hundreds (515 at most in eight seasons)
-- and never near 10^6, and a category part has at most 2 terms. So a whole weight of at
-- most 10^6 keeps every sum below 2 * 10^6 * 10^6 = 2 * 10^12, far below 2^53. A
-- fractional weight (1/3 for innings, say) or a huge one would make them depend on row
-- order, and the build fails here by name instead. The sums then need fo_sum_in_order.

select
    platform,
    stat_key,
    part,
    component,
    weight
from {{ ref('int_fantasy__stat_components') }}
where
    weight <> floor(weight)
    or abs(weight) > 1000000
