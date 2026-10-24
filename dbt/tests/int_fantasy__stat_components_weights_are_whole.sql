-- Every weight in int_fantasy__stat_components is a whole number. Returns each row whose
-- weight is not, with its platform, stat_key, part and component.
--
-- rec_fantasy__category_wins_added sums weight * swapped_total three times without an
-- `order by` (an `order-exempt:` claim, ADR 0046). Those sums are exact in any order only
-- while every weight is whole: whole weights times whole totals stay whole and far below
-- 2^53. A platform whose rules carry a fractional weight, 1/3 for innings say, would make
-- them depend on row order, and the build fails here by name instead. The sums then need
-- fo_sum_in_order.

select
    platform,
    stat_key,
    part,
    component,
    weight
from {{ ref('int_fantasy__stat_components') }}
where weight <> floor(weight)
