-- The slot a player was actually in is one of the slots he was eligible for.
--
-- ESPN will not let a manager put a shortstop in the catcher slot, so this must hold for
-- every roster entry -- and it does: verified across all 55,653 entries of the 2026
-- season with zero exceptions before the test was written.
--
-- Its real job is to catch the two ways the pair of models could drift apart. If the
-- eligibility parse silently loses elements of the array, or if the two models ever read
-- different roster snapshots for the same period, entries start appearing whose actual
-- slot is not among their eligible ones. Neither failure is visible in a row count.

select
    entries.league_id,
    entries.season,
    entries.scoring_period,
    entries.team_id,
    entries.espn_player_id,
    entries.lineup_slot_id
from {{ ref('stg_espn__roster_entries') }} as entries
left join {{ ref('stg_espn__roster_entry_slots') }} as slots
    on slots.league_id = entries.league_id
    and slots.season = entries.season
    and slots.scoring_period = entries.scoring_period
    and slots.team_id = entries.team_id
    and slots.espn_player_id = entries.espn_player_id
    and slots.lineup_slot_id = entries.lineup_slot_id
where slots.lineup_slot_id is null
