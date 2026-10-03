-- R6.1: fct_transaction_impact has exactly one row per row of int_fantasy__transactions.
-- Returns a row, with both counts, when they differ. The unique test catches a doubled
-- transaction; this catches one lost or fanned out by a join.

with impact as (

    select count(*) as impact_rows
    from {{ ref('fct_transaction_impact') }}

),

interface as (

    select count(*) as transaction_rows
    from {{ ref('int_fantasy__transactions') }}

)

select
    impact.impact_rows,
    interface.transaction_rows
from impact
cross join interface
where impact.impact_rows <> interface.transaction_rows
