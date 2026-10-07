# Scoring-period dates — design

Issue: #70 · Requirements: [requirements.md](requirements.md) · Tasks: [tasks.md](tasks.md)

## Overview

ESPN's status block cannot date a finished season: its period counter stops, and
nothing in a capture says whether it had stopped when the capture was taken. So the
date of a scoring period stops coming from ESPN. Period 1 of a league-season is the
first official date of MLB's regular season, and each later period is the next calendar
day. The settings capture supplies only the number of periods. Whether that rule is
right is then checked on every build against something it does not use: ESPN's own
per-game stat lines, which say which games ESPN scored on which period. On 2026 the two
agree on all 177 periods that have a game. The audit keeps comparing the counter with
opening day, but only for captures taken while the season was in progress.

One model changes its derivation and keeps its name, grain and columns, so nothing
downstream is edited.

## Alternatives considered

| | A — MLB opening day (chosen) | B — earliest settings capture | C — only captures with `latest <= final` | D — fit the offset to ESPN's game lines | E — the dates ESPN publishes |
|---|---|---|---|---|---|
| Right for 2026 | yes | yes, because the first capture was taken while the counter moved | no dates: all 5 captures are past the final period | yes | yes: agrees with A on all 184 periods with a game |
| Right for a season first fetched after it ended (#57) | yes | no | no dates | only with rosters landed | yes: 2018, 2024 and 2025 checked |
| Depends on when or how often settings are fetched | no | yes, on the first fetch | yes | no | no |
| Reads another source | MLB schedule | no | no | MLB schedule and every roster payload | new ESPN endpoint |
| A wrong mapping is caught by | the game-line test (R3.1) | the opening-day test, period 1 only | the same | nothing: it is the evidence | the game-line test |
| New ingestion | no | no | no | no | yes |

**A — MLB opening day.** Period 1 is the earliest `official_date` of the season's
regular-season games. It needs nothing but the schedule, which is landed before any
roster, and it reads the same for 2026 today, for 2027 in April and for 2018 fetched in
2027. Its two assumptions (ESPN starts on MLB's first game; one period is one day) are
what the game-line test checks.

**B — earliest settings capture.** One line changed in the model. It gives 2026-03-25
because the landing zone happens to start on 2026-09-26, when the counter still moved.
Had the first fetch been on 2026-10-06, it would be wrong with no way to tell from ESPN
alone, and that is the situation of every historical season.

**C — only in-progress captures.** The principled ESPN-only rule: trust the counter
only while `latest <= final`. For 2026 there is no such capture, so there would be no
dates and no warehouse. It survives as the audit's rule (ADR 0022), where having nothing
to compare is acceptable.

**D — fit the offset.** Pick the offset at which ESPN's distinct games per period match
MLB's played games per date. This is the strongest evidence available, and it is why it
should be a test: as the rule, a mismatch could only move the dates quietly, every date
would wait on parsing 180 roster payloads of 2.3 MB, and a league-season without rosters
would have no dates.

**E — the dates ESPN publishes.** ESPN's game-level season resource
(`view=proTeamSchedules_wl`) lists every pro game with its start time and scoring
period, without credentials. Checked on 2026-10-07 for 2026, 2025, 2024 and 2018 (four
requests, nothing landed): every period with a game is one Eastern date, one period per
day from period 1, and period 1 is the first regular-season game, international openers
included. It is ESPN's own answer and it agrees with A everywhere it was checked. It
loses for now on scope alone: a new endpoint, staging model and fixture, while a P1
holds the warehouse. The owner chose A now and E as a follow-up (#73).

## Decisions

| ADR | Decision | Status |
|---|---|---|
| [0021](../../adr/0021-a-scoring-period-is-dated-from-mlbs-schedule.md) | A scoring period is dated from MLB's schedule, not from ESPN's period counter | accepted |
| [0022](../../adr/0022-espns-period-counter-is-not-a-date-after-the-final-period.md) | ESPN's period counter is not read as a date after the final period | accepted |

## Detailed design

### `stg_espn__scoring_periods`

Grain, key and columns are unchanged: one row per (`league_id`, `season`,
`scoring_period`), with `scoring_date`.

```sql
with league_seasons as (
    select league_id, season, final_scoring_period
    from {{ ref('stg_espn__league_settings') }}
),

opening_days as (
    select season, min(official_date) as opening_day
    from {{ ref('stg_mlb__games') }}
    where game_type = 'R'
    group by season
),

periods as (
    select league_seasons.league_id, league_seasons.season,
           generate_series as scoring_period
    from league_seasons,
        generate_series(1, league_seasons.final_scoring_period)
)

select
    periods.league_id,
    periods.season,
    periods.scoring_period,
    opening_days.opening_day + ((periods.scoring_period - 1)::integer) as scoring_date
from periods
left join opening_days
    on opening_days.season = periods.season
```

- The `left join` is deliberate (R1.5): a league-season whose MLB season is not loaded
  keeps its rows with a null date, and the `not_null` test on `scoring_date` fails. An
  inner join would produce no rows and let downstream models build empty.
- Opening day counts every regular-season game, played or not, so the mapping exists
  before the first pitch of 2027.
- `fo_eastern_date` is no longer used by this model. It stays: transactions use it.
- The header comment is rewritten to say why the date comes from MLB, with the five
  captures as the evidence, and that the model is the one staging model that reads
  another source's staging model. In dbt, staging models conventionally read only their
  own source and sources meet in the intermediate layer; this one is the exception
  because its whole job is the bridge. The owner chose on 2026-10-07 to leave it in
  staging: if #73 makes ESPN's own schedule the rule, the model reads only ESPN again
  and the exception ends without a rename.

`stg_espn__league_settings` keeps its SQL. Its YAML gains a description for
`latest_scoring_period` (R2.1).

### The game-line test

`dbt/tests/stg_espn__scoring_periods_agree_with_espn_game_lines.sql`, a singular test
(a query that fails the build if it returns any row):

```sql
with espn_games as (
    select league_id, season, scoring_period,
           count(distinct espn_game_id) as espn_games
    from {{ ref('stg_espn__player_game_stats') }}
    group by league_id, season, scoring_period
),

mlb_games as (
    select official_date, count(*) as mlb_games
    from {{ ref('stg_mlb__games') }}
    where game_type = 'R' and is_played
    group by official_date
)

select espn_games.*, periods.scoring_date, mlb_games.mlb_games
from espn_games
inner join {{ ref('stg_espn__scoring_periods') }} as periods
    using (league_id, season, scoring_period)
left join mlb_games
    on mlb_games.official_date = periods.scoring_date
where espn_games.espn_games > coalesce(mlb_games.mlb_games, 0)
```

It is a comparison of counts, so it is a partial signal: it cannot show that the games
ESPN scored on a period are the games MLB played that day, only that there were enough
of them. Game ids cannot be compared, because ESPN's are not MLB's. The player-level
evidence already exists in `rec_espn__player_day_differences`, which compares every
started player-day with ESPN's line for that period: 22 rows on 2026, each an official
scoring change. The last task reads it before and after.

It is `>` and not `!=` because ESPN's lines cover only rostered players: a game in which
no rostered player appeared would be missing from ESPN's side and is no error. On 2026
the two are equal on every period, which the expected values record. It reads the
already-built `stg_espn__player_game_stats` table, so it costs no roster parse.

In CI it passes without testing anything: the fixture rosters carry no game lines
(`stg_espn__player_game_stats` has 0 rows there). The same would happen to a real season
if ESPN changed the shape of its stat lines. So a second singular test,
`stg_espn__scoring_periods_have_game_lines_to_check.sql`, returns every scoring period of
a league-season with roster entries whose date has a played MLB game and which has no
ESPN game line. It is configured `severity: warn`: in dbt a test's severity decides
whether returned rows fail the build or only print a warning. It warns because it is
expected in CI (2 rows, one more warning beside the 5 there today) and for a day or two
in season, before a period's roster is captured again after it closes. On the 2026
season it returns nothing. The unit tests are what CI holds the rule to.

Giving the fixtures game lines would remove the CI warning, and was considered. It is not
a small change: the roster fixtures are built from real periods 100 and 101 (2026-07-02
and 2026-07-03) while the MLB fixture games are from 2026-04-29 and 2026-04-30, so lines
from those rosters would fail this very test on fixture period 2 (13 ESPN games against
11 MLB games). Making the fixture season one real pair of days is #74; the owner split
it out on 2026-10-07. The warning has a precedent in `rec_espn__every_side_is_verified`,
which warns in CI for the same reason.

### The audit

In `_check_league` (`ingestion/src/front_office/audit.py`), the anchor block becomes:

- Opening day is taken by the model's rule: `check_mlb` returns the earliest official
  date among all regular-season games of the newest schedule, where today it takes only
  played games (R4.7). A schedule landed in March 2027 then gives the audit the same
  opening day as the model.
- Split `status_by_run` three ways: in progress (`latestScoringPeriod <=
  finalScoringPeriod`), past the final period, and unreadable (either field missing or
  not an integer). An unreadable status → WARN naming the capture, and it is counted in
  neither group (R4.8).
- `opening_day is None` → ERROR: `no MLB schedule landed, so scoring periods cannot be
  dated` (R4.4).
- For each in-progress capture, the implied date is `eastern_date(run)` −
  (`latestScoringPeriod` − 1) days, as today. Any that differs from opening day → one
  ERROR listing `run -> date` for each, and opening day (R4.2).
- All in-progress captures agree with opening day → INFO with their count (R4.5).
- Past the final period, if any → INFO: `N settings capture(s) taken after the final
  period; their period counter is not compared with a date` (R4.3).

Captures no longer need to agree with each other as a separate check: each is compared
with opening day, so two that disagree cannot both pass.

The rest of `_check_league` (`newest_status`, `season_over`, roster finality) is
untouched.

### What is not changed, and why it is safe

`int_fantasy__roster_days` and `int_fantasy__matchup_periods` join on
`scoring_period` and take `scoring_date` from this model. Its output for 2026 is the
same 180 rows, so they build the same rows from the same load.

`scripts/make_fixtures.py` renumbers the fixture season to periods 1 and 2 and its MLB
games are on 2026-04-29 and 2026-04-30, so opening day in CI is 2026-04-29 and the
fixture dates do not move. Only the comment explaining `FIXTURE_FETCHED_AT` is out of
date; the stamp itself stays, since changing it would rename every fixture capture.

## Test strategy

| Requirement | Test | Catches |
|---|---|---|
| R1.1, R1.2, R1.4, R5.1 | unit test `scoring_period_dates_do_not_depend_on_the_settings_capture` | #70 itself: a counter of 188 fetched on 2026-10-07 moving period 1 off 2026-03-25 |
| R1.3, R5.2 | unit test `scoring_periods_run_to_each_leagues_own_final_period`, given MLB rows | one series generated to the longest league's final period |
| R1.6, R5.3 | unit test with seasons 2026 and 2027 | a 2027 league dated from 2026's opening day |
| R1.1, R5.3 | unit test with an earlier game of another `game_type` | spring training or an exhibition moving opening day, if one is ever landed |
| R1.5, R5.3 | unit test with no MLB rows for the season | an inner join dropping the league-season silently |
| R2.1 | review of the YAML | — |
| R2.2 | `not_null` on `final_scoring_period` | a league-season that would silently get no periods |
| R3.1, R3.5 | singular test `stg_espn__scoring_periods_agree_with_espn_game_lines` | a whole-season shift of the mapping: 63 to 69 failing periods at ±1, +8, +9 days on 2026. A partial signal: counts, not games |
| R3.4 | singular test `stg_espn__scoring_periods_have_game_lines_to_check`, `severity: warn` | R3.1 passing because it had nothing to compare |
| R3.2 | `stg_espn__scoring_periods_start_on_opening_day`, SQL unchanged | an off-by-one in R1.2; no MLB season loaded |
| R3.3 | the three existing tests, unchanged | gaps, repeats, wrong length |
| R4.1–R4.5, R5.4 | pytest in `test_audit.py`: the 2026 world (3 agreeing and 2 disagreeing captures, all past final) audits without error; an in-progress capture that disagrees is an error; in-progress captures that agree are information; no MLB schedule is an error; a schedule with no game played yet gives an opening day (R4.7); a status without `finalScoringPeriod` is a warning and is not compared (R4.8) | a stopped counter reported as an error; a moving counter that disagrees going unreported |
| R4.6 | the existing roster and transaction audit tests, unchanged | the anchor change reaching the finality logic |
| Expected values | the last task, on the real season | correct on fixtures, wrong on the season |

## Risks

- MLB's schedule does not file an international opener as regular season, so opening
  day is a week late for 2024 or 2025 — unknown, only 2026 is landed; ESPN's side is
  checked for 2018, 2024, 2025 and 2026 — the game-line test fails for a league-season
  with rosters; for one without, #73 and #57 (ADR 0021).
- The game-line test proves nothing in CI — certain — stated in the test's header; the
  unit tests cover the rule and the real-season build covers the mapping.
- An ESPN line for a suspended game is scored on the day it resumed, not its official
  date — one such game in 2026 (824912), and all 177 periods still agree — accepted; a
  failure would name the period.
- Loading the two frozen runs moves mart numbers for reasons unrelated to dates (new
  roster captures of periods 179 and 180, 27 boxscores) — likely, small — the last task
  compares the model before and after the load separately from the marts, and reports
  what moved.

## Open questions

- **When and why the counter stops.** 2026 suggests the day after MLB's last
  regular-season game. One season; nothing depends on it after this spec.
- **When the counter turns over in a day.** `standingsUpdateDate` moves at about 04:30
  Eastern. If the counter does too, an in-progress capture taken between midnight and
  then implies yesterday, and R4.2 reports an error. The first week of 2027 resolves it
  (with #66).
- **The roster re-check needs `latest > period + 7`** (ADR 0018). The counter stopped at
  final + 8 in 2026, just enough. A league whose final period is closer to the end of
  MLB's season could never settle its last periods. Not this spec: #75.
- **Whether MLB files the Tokyo and Seoul openers as `game_type = 'R'`.** Matters for
  2024 and 2025 only; for #57.
- **`firstScoringPeriod`** is 1 in all five captures and the model generates from 1, as
  it does today. Periods are game-wide, so a league that starts at a later period would
  still have the right dates for the periods it has, and rows for periods it does not.

## Review log

| Source | Finding | Resolution |
|---|---|---|
| design-review | F1 (P1): the audit takes opening day from played games, the model from all scheduled games; a schedule landed before the season would be "no schedule" to the audit | Changed: R4.7, the audit uses the model's rule, with a test |
| design-review | F2 (P1): the game-line test passes when there are no game lines, so "checked on every build" is not true | Changed: the goal is reworded; R3.4 adds a warning for every period R3.1 could not check. A warning and not a failure because the fixtures have no game lines; the owner chose the warning on 2026-10-07 and split the fixture change into #74 |
| design-review | F3 (P2): a status with no `finalScoringPeriod` was counted as past the final period | Changed: R4.8, a third group reported as a warning; R2.2 adds `not_null` on `final_scoring_period` |
| design-review | F4 (P2): a count inequality cannot catch every misalignment | Changed: R3.5 and the design call it a partial signal; the player-level reconciliation (22 rows) is added to the expected values |

## Amendments
