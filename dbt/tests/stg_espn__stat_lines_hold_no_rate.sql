-- Neither ESPN line model holds a rate stat. Returns each (model, stat_id) that does, with
-- the number of rows.
--
-- ESPN writes a value for a rate (AVG, ERA, K/BB...) even when its denominator is zero, and
-- the encoding changes by season: the largest double in 2018, NaN for RC in 2021, and 0.0
-- from 2019, which cannot be told from a real zero. The project keeps components, never
-- rates (AGENTS.md, rule 4), and ADR 0099 keeps ESPN's rates out of
-- stg_espn__player_game_stats and stg_espn__matchup_player_lines: the 15 stat ids with
-- is_rate in the espn_stat_ids seed. This fails if either model stops dropping them, or if
-- a rate is staged some other way. It cannot see a rate the seed does not name; the
-- finite-values test catches one only when ESPN writes it as a sentinel or NaN.
--
-- The CI fixtures hold no rate row once the models filter, so
-- dbt/plants/stg_espn__stat_lines_hold_no_rate.yml plants one in each.

with stat_rows as (

    select
        'stg_espn__player_game_stats' as model,
        stat_id
    from {{ ref('stg_espn__player_game_stats') }}

    union all

    select
        'stg_espn__matchup_player_lines' as model,
        stat_id
    from {{ ref('stg_espn__matchup_player_lines') }}

)

select
    stat_rows.model,
    stat_rows.stat_id,
    count(*) as row_count
from stat_rows
inner join {{ ref('espn_stat_ids') }} as stat_ids
    on stat_ids.stat_id = stat_rows.stat_id
where stat_ids.is_rate
group by stat_rows.model, stat_rows.stat_id
