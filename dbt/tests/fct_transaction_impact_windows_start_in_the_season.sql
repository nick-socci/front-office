-- R6.4: no window starts before the first scoring date. A pre-season transaction would
-- otherwise open a window over days that have no matchups and no started players.
-- Returns the offending transactions.

select
    transaction_id,
    movement,
    transaction_date,
    window_start
from {{ ref('fct_transaction_impact') }}
where window_start < (
    select min(scoring_date)
    from {{ ref('int_fantasy__matchup_periods') }}
)
