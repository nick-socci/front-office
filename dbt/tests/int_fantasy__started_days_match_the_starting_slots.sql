-- Started player-days equal the roster days whose slot actually scores.
--
-- is_started comes from the espn_lineup_slots seed, where exactly bench and injured
-- list are false. If that column were ever wrong -- a new slot added to the seed with
-- the wrong flag, say -- every category total downstream would silently include
-- benched players, and every number would still look plausible.
--
-- 38,665 of 55,653 roster days were starts in 2026. This asserts the relationship
-- rather than the number, so it survives a re-backfill.

with expected as (

    select count(*) as days
    from {{ ref('int_fantasy__roster_days') }}
    where is_started

),

actual as (

    select count(*) as days
    from {{ ref('int_fantasy__started_player_days') }}

)

select
    expected.days as expected_days,
    actual.days as actual_days
from expected
cross join actual
-- Zero started days would make the equality prove nothing, so it fails too.
where
    expected.days != actual.days
    or expected.days = 0
