-- Every stat value in both ESPN line models is an ordinary number. Returns each row whose
-- value is NaN, infinite, or at least 1e300 in size, with its model and stat id.
--
-- ESPN has written an undefined rate as an x/0 sentinel (the largest double, 1.79e308, in
-- the 2018 game lines; the string "Infinity" in the matchup lines) and as NaN (RC, 2021).
-- Staged as a count, either would poison any sum it reaches: two largest doubles overflow.
-- ADR 0099 keeps the named rates out of both models; this holds every other stat to the
-- same standard, so a sentinel or a NaN in any stat fails here (spec 0194). A null
-- value is not a failure: the game lines can hold one from fo_safe_cast, and the matchup
-- lines drop theirs.
--
-- It cannot catch an unlisted rate that ESPN writes as 0.0, which is how ESPN has written
-- an undefined rate since 2019: that is a finite number and looks like a count of zero.
-- Only naming the rate in the seed's is_rate column keeps it out (ADR 0099).
--
-- The CI fixtures hold no such value, so
-- dbt/plants/stg_espn__stat_lines_hold_finite_values.yml plants one in each model.

with stat_rows as (

    select
        'stg_espn__player_game_stats' as model,
        stat_id,
        stat_value
    from {{ ref('stg_espn__player_game_stats') }}

    union all

    select
        'stg_espn__matchup_player_lines' as model,
        stat_id,
        stat_value
    from {{ ref('stg_espn__matchup_player_lines') }}

)

select
    model,
    stat_id,
    stat_value
from stat_rows
where
    not {{ fo_is_finite('stat_value') }}
    or abs(stat_value) >= 1e300
