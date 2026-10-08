# Past seasons' matchup totals — tasks

Issue: #85 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #85 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADR 0026.

1. Record the starting point — `judgment` — expected values
   - Copy `data/warehouse.duckdb`; dump the views' rows from it (spec 0070's amendment);
     record CI's counts and warnings.
   - Verify: posted on #85.
2. `--only matchups` — `impl` — R1.1–R1.5, R4.1
   - pytest with a fake transport first, seen to fail; then `cli.py`, with the line in
     the audit's help (R1.5).
   - Verify: `uv run pytest`, ruff, mypy. No request to ESPN.
3. The coverage model — `impl` — R2.1, R2.6, R4.2
   - Unit tests and the R2.6 test first; then `int_fantasy__league_seasons` with its
     contract and header.
   - Verify: CI build passes; one row, `has_rosters` true, for the fixture league-season.
4. Coverage applied — `impl` — R2.2–R2.5, R2.7, R4.3, R5.4
   - The R4.3 and R5.4 tests first. Then the joins and restrictions of the design's table, each
     with a line in the model's header saying why.
   - Verify: CI build unchanged in counts and warnings apart from the tests added; every
     CI relation identical to the starting point.
5. Land 2025 — `judgment` — R3.1, R5.1
   - `uv run front-office backfill mlb --season 2025 --only schedule` first, then `uv
     run front-office backfill espn --season 2025 --only matchups`. Two public requests
     and two authenticated ones. MLB's schedule goes first because it answers the Tokyo
     question before anything is sent with the login.
   - Verify: four captures; whether MLB's schedule has regular-season games on
     2025-03-18 and 2025-03-19. If it has none, stop: the fixture of task 6 cannot be
     built as designed, and the owner decides.
6. The 2025 fixture season — `impl` — R3.1–R3.5, R4.4
   - pytest first, including that the multi-fixture generator takes its sources from
     `BASE_SEASON` only when another season is in the base tree; then the season
     argument in `scripts/make_fixtures.py`, the filter in
     `scripts/make_multi_fixtures.py`, regeneration of both trees, and ("111111", 2025)
     in the isolation check.
   - Verify: `git status fixtures` shows only new 2025 directories and their copies in
     the multi tree; the 2026 fixtures are byte for byte; privacy test passes; the keys
     of every new file are read before committing.
7. Gates with the past season — `judgment` — R2.2–R2.5, R4.3, R4.4
   - `.agentic/gates`.
   - Verify: CI passes with 3 warnings; isolation 0 over 5 league-seasons. A failure
     for the 2025 fixture season in a test not in the design's table is R5.3.
8. Land 2018 to 2024 — `judgment` — R5.1
   - The two commands of task 5 for each season: fourteen authenticated requests and
     fourteen public ones.
   - Verify: per season, three ESPN captures and one MLB schedule; posted on #85.
9. (last) Verify against the real seasons — `judgment` — R2.7, R5.2–R5.5, expected values
   - `uv run front-office load`, a full `dbt build`. Compare every model's 2026 rows
     with the starting point. Record, per season, the rows of the every-season models,
     the scored categories, the final period, period 1, MLB's opening day and the number
     of decided two-sided matchups (R5.5).
   - Verify: every expected value, as a comment on #85. Anything that fails outside the
     design's table: stop and take it to the owner with the season, the test and the
     rows.
