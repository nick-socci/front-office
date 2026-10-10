-- Where each candidate could have started that day, and what his day was worth there (#12).
--
-- One row per team-day, player and starting slot such that the league uses the slot, ESPN
-- lists the player as eligible for it in that period's roster of that team, and the slot's
-- role credits a side he played that day. A player who did not play that side has no option
-- in that slot, so a slot nobody can fill with a line is simply idle. The solver downstream
-- chooses among these pairs; nothing is chosen here.
--
-- THE OPTIONS FEED A HINDSIGHT-OPPORTUNITY COMPARISON, not a measure of manager skill: the
-- values are known only after the games, and nothing here says a manager could have known
-- them.
--
-- ELIGIBILITY IS ESPN'S AS FETCHED (ADR 0038). ESPN returns a player's current eligibility
-- whatever period is requested (#52), so for a backfilled season it is the eligibility as of
-- eligibility_fetched_at, not of the day, and a move that was not legal on the day can look
-- legal. That is why the fetch time is carried on every row. Eligibility only grows in a
-- season, so the slot a player actually sat in is inside it (R2.4's singular test holds
-- that to the data). Measured on the 2026 backfill (2026-10-09): scoring periods 1 to 178
-- carry the eligibility of 2026-09-26, and periods 179 and 180, whose rosters were captured
-- again once settled, that of 2026-10-07. A team-day has one roster and so one fetch time.
--
-- Candidates (R1.1) are the roster days in a starting slot, or in a bench slot that is not an
-- injured-list slot (is_injured_list_slot in the espn_lineup_slots seed), selected exactly as
-- int_fantasy__candidate_day_values selects them. is_started is the roster day's: he was in a
-- starting slot. is_actual is that his slot is this option's slot, so a bench player has none
-- and a started player has it on his own slot only.
--
-- option_value is the day_value of the side the role credits (hitter: batting, pitcher:
-- pitching) and day_kind that side's kind (batting, start or relief). option_value is carried
-- as it is, null when the day value is unknown: a later model reads the null, and it is never
-- coalesced here.
--
-- THE RULE THESE ARE CHOSEN UNDER (R3.1, ADR 0037): a starter who played is replaced only by
-- another player who played, and a tie keeps the actual lineup. That is why a player with no
-- line on a slot's side has no option there, and why injured-list slots give none. The
-- league's limit on pitcher starts is not applied: day_kind is carried so the starts of each
-- lineup can be counted downstream, not so that they can be capped.

{{ config(materialized='table') }}

with candidates as (

    select
        days.platform,
        days.league_id,
        days.season,
        days.scoring_date,
        days.scoring_period,
        days.fantasy_team_id,
        days.platform_player_id,
        days.roster_slot_id,
        days.is_started
    from {{ ref('int_fantasy__roster_days') }} as days
    inner join {{ ref('espn_lineup_slots') }} as slots
        on slots.lineup_slot_id = days.roster_slot_id
    where days.is_started or (days.slot_role = 'bench' and not slots.is_injured_list_slot)

)

select
    candidates.platform,
    candidates.league_id,
    candidates.season,
    candidates.scoring_date,
    candidates.scoring_period,
    candidates.fantasy_team_id,
    candidates.platform_player_id,
    lineup_slots.lineup_slot_id,
    lineup_slots.lineup_slot,
    lineup_slots.slot_role,
    day_values.day_value as option_value,
    day_values.day_kind,
    candidates.is_started,
    candidates.roster_slot_id = lineup_slots.lineup_slot_id as is_actual,
    eligible.fetched_at as eligibility_fetched_at
from candidates
inner join {{ ref('stg_espn__roster_entry_slots') }} as eligible
    on eligible.league_id = candidates.league_id
    and eligible.season = candidates.season
    and eligible.scoring_period = candidates.scoring_period
    and eligible.team_id = candidates.fantasy_team_id
    and eligible.espn_player_id = candidates.platform_player_id
inner join {{ ref('int_fantasy__lineup_slots') }} as lineup_slots
    on lineup_slots.platform = candidates.platform
    and lineup_slots.league_id = candidates.league_id
    and lineup_slots.season = candidates.season
    and lineup_slots.lineup_slot_id = eligible.lineup_slot_id
inner join {{ ref('int_fantasy__candidate_day_values') }} as day_values
    on day_values.platform = candidates.platform
    and day_values.league_id = candidates.league_id
    and day_values.season = candidates.season
    and day_values.scoring_date = candidates.scoring_date
    and day_values.fantasy_team_id = candidates.fantasy_team_id
    and day_values.platform_player_id = candidates.platform_player_id
    and day_values.side = case lineup_slots.slot_role when 'hitter' then 'batting' when 'pitcher' then 'pitching' end
