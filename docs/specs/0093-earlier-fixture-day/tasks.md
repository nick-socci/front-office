# An earlier fixture day — tasks

Issue: #93 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #93 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADR 0030.

1. Record the starting point — `judgment` — expected values
   - On `main`: the CI build's counts and its four warnings with their rows, the pools,
     the null counts of the two value facts, started player-days, fixture sizes.
   - Verify: the "now" column of the expected values, posted on #93, with the two cells
     marked as not recorded filled in.
2. The script's numbering and boxscore choice — `impl` — R1.1–R1.5, R2.1–R2.4, R6.1
   - pytest first, seen to fail: offset numbering for (31, 36, 37) and (1, 2); settings
     span; the earlier date not displacing an existing boxscore; a history game not
     landed stops generation. Then the constants, the two helpers and
     `build_mlb_boxscores`.
   - Verify: `uv run pytest ingestion/tests/test_make_fixtures.py`; ruff and mypy clean.
     No fixture regenerated yet.
3. The purpose check — `impl` — R3.1, R6.1
   - pytest first, seen to fail, one made-up landing zone each, asserting the message:
     no start in the earlier game; an earlier start with no outs; no later start; a
     later start by a pitcher rostered that day. Then the check, called from `main()`
     before any write.
   - Verify: as task 2.
4. Regenerate — `impl` — R4.1–R4.5
   - `git rm -r` the base tree's `scoring_period=2` roster directory, then
     `uv run python scripts/make_fixtures.py`, then
     `uv run python scripts/make_multi_fixtures.py`.
   - Verify: `git status --short fixtures/landing` lists exactly the files of R4.1;
     `git diff --quiet` on the two existing boxscores, the correction, teams,
     transactions and every 2025 fixture; the multi generator prints 2027-04-23. If
     anything else changed, or the multi script fails, stop and report.
5. Tests of the committed fixtures — `impl` — R3.2, R6.2
   - Update the three pytest to periods 1, 6, 7; add the committed-files form of the
     purpose check.
   - Verify: `uv run pytest`, including the privacy test.
6. The words — `impl` — R6.3
   - Verify: `git diff dbt` shows comment and description lines only.
7. (last) Verify — `judgment` — R5.1–R5.4, expected values
   - `.agentic/gates`; query `dbt/ci.duckdb` for every row of the expected values;
     confirm on `data/warehouse.duckdb` that the real start pool is unchanged.
   - Verify: every row recorded as a comment on #93. A warning that was not expected to
     go or stay, or a count that differs, is reported with its cause before the PR is
     opened.
