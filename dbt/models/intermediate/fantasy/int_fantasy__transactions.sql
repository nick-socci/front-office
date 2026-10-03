-- One row per transaction message: a player added to or dropped from a fantasy roster,
-- with the fantasy team that did it.
--
-- WHY the acting team is not just `to`. ESPN's `to`, `from` and `for` fields mean
-- different things on different message types (ADR 0004). On adds, and on drops of type
-- 179 and 181, `to` is the acting team. On a type-239 drop `to` is not, `for` is, and
-- `from` is the lineup slot the player left rather than a team. Which field to read is
-- data, not SQL: the espn_activity_types seed carries team_field, movement and method
-- per message type, so this model holds no message type ids. A type the seed has no rule
-- for (a trade, or one ESPN adds later) gets a null movement and fails the not_null test
-- on it, rather than being given a team by guess.
--
-- Carries no league_id or season, because staging has neither (#28). The marts join it to
-- the single league-season on team and player id, and #28 must land before a second
-- league or season is loaded, or those joins would mix leagues.

{{ config(materialized='table') }}

with transactions as (

    select
        transactions.transaction_id,
        transactions.topic_id,
        transactions.transacted_at,
        transactions.transaction_date,
        transactions.espn_player_id,
        transactions.message_to,
        transactions.message_from,
        transactions.message_for,
        rules.movement,
        rules.method,
        rules.team_field
    from {{ ref('stg_espn__transactions') }} as transactions
    left join {{ ref('espn_activity_types') }} as rules
        on rules.message_type_id = transactions.message_type_id

)

select
    'espn' as platform,
    transactions.transaction_id,
    transactions.topic_id,
    transactions.transacted_at,
    transactions.transaction_date,
    transactions.espn_player_id as platform_player_id,
    case transactions.team_field
        when 'to' then transactions.message_to
        when 'for' then transactions.message_for
    end as fantasy_team_id,
    transactions.movement,
    transactions.method,
    -- `from` is a slot id only where the acting team is read from `for`.
    case when transactions.team_field = 'for' then slots.slot_abbrev end as dropped_from_slot
from transactions
left join {{ ref('espn_lineup_slots') }} as slots
    on slots.lineup_slot_id = transactions.message_from
