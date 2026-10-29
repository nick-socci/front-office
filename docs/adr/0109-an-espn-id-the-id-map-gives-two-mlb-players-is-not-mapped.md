# 0109. An ESPN id the id map gives to two MLB players is not mapped

- Status: proposed
- Date: 2026-10-28
- Spec: [0141-total-tie-breaks](../specs/0141-total-tie-breaks/design.md) · Issue: #141

## Context

The id map's newest capture lists ESPN id 5214984 twice: as Jonah Tong (MLB 804636, NYM)
and as Michael Tonkin (MLB 543859, team `N/A`). Both rows are `P` and come from one capture,
so `stg_idmap__players`' order (`fetched_at desc, POS desc`) cannot choose (spec 0141, C3).
DuckDB keeps Tong. The league rostered "Jonah Tong" under that id 51 times in 2025 and 2026
(C4). A warehouse that kept Tonkin would credit Tong's days to Tonkin. Under ADR 0107 this
tie stops the build until a rule decides it.

The other duplicate in the map is Ohtani: ESPN id 39832, one MLB id, listed as `P` and as
`DH`. The owner's rule of 2026-10-11 splits that by position text. It is not a claim about
the player.

`int_fantasy__player_crosswalk` resolves an ESPN id by the map first. Failing that, it
matches the accent-stripped name, if exactly one MLB player of that season has it. "Jonah
Tong" belongs to one MLB player, 804636, in both 2025 and 2026 (C4).

## Decision drivers

- No wrong player, silently.
- A rule general across leagues and seasons, not fitted to one row.
- What an ambiguous mapping did stays visible downstream.

## Considered options

1. **Leave the id out of the map.** An ESPN id that the newest capture lists with more
   than one distinct MLB id is dropped from `stg_idmap__players`. The crosswalk's name
   fallback then decides, or leaves the player `unresolved`. Ohtani's rows share an MLB id,
   so they are untouched.
2. **The higher MLB id wins**, after `POS`. Tong today (804636 > 543859). A rule with no
   claim behind it, like the Ohtani one.
3. **A row with a club wins over a `N/A` team**, then the higher MLB id. Tong today. It reads
   meaning into `TEAM`, which describes the player now, not when the season was played.
4. **An override seed**, kept by hand: ESPN id → MLB id, with its evidence.

## Decision

Chosen by the owner on 2026-10-28, as recommended: **option 1**.

A map entry that names two players does not map the id. Treating it as missing is how the
model already treats an entry that names none ("a crosswalk entry that maps nothing is not
a mapping"). The fallback was built for this case, restricted to names that belong to one
player in that season. The result says how the player was matched: Tong keeps MLB id
804636, and his rows show `unambiguous_name` where they showed `crosswalk_id` (51 roster
days, 42 started days, 2 rows of `dim_player_league_seasons`, C4). If the name were
ambiguous too, he would show as `unresolved` rather than as the wrong player.

Options 2 and 3 pick Tong today, but by a rule that would pick the wrong player as often as
the right one on the next such error. Option 4 is a correct answer kept by hand, one row
at a time, for every league. It suits an error the fallback cannot resolve, and nothing
here needs it yet.

## Consequences

- Good: no ambiguous mapping can choose a player by row order or by a guess, and the
  resolution label shows which players took the fallback.
- Bad / accepted cost: `stg_idmap__players` loses one row (3,657 → 3,656). Three relations
  change the label of ESPN 5214984's rows, and none changes a player id.
- Bad / accepted cost: a player whose name is also ambiguous becomes `unresolved` and loses
  his MLB stats until the map is corrected.
- Follow-ups: if that happens to a rostered player, option 4 (an override seed) is the next
  record.
