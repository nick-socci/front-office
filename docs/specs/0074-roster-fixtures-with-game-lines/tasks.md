# Roster fixtures on the fixture days — tasks

Issue: #74 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #74 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADR 0025.

1. Record the starting point — `judgment` — expected values
   - On `main`: the CI build's counts and its six warnings with their rows, the roster
     fixtures' entry counts and sizes, `rec_espn__player_day_differences` in CI.
   - Verify: the "now" column of the expected values, posted on #74; the second
     period's entry count filled in.
2. The script — `impl` — R1.1–R1.3, R2.1–R2.4, R5.2
   - pytest first, seen to fail: the date check on a made-up landing zone; the line
     filter and allowlist on a made-up roster entry. Then the constant, the check,
     `ESPN_STAT_LINE_FIELDS` and `build_espn_rosters`.
   - Verify: `uv run pytest ingestion/tests/test_make_fixtures.py`; ruff and mypy clean.
     No fixture regenerated yet.
3. Regenerate — `impl` — R3.1–R3.4
   - `uv run python scripts/make_fixtures.py`, then `uv run python
     scripts/make_multi_fixtures.py`.
   - Verify: `git status --short fixtures` lists exactly 3 and 7 changed payloads and no
     new or deleted file. If anything else changed, stop and report. The privacy test
     passes.
4. Tests of the committed fixtures — `impl` — R1.1, R5.1
   - The pytest of the committed rosters against the committed pro schedule.
   - Verify: `uv run pytest`.
5. The words — `impl` — R5.3
   - The three test headers and the script's comments. No SQL changes.
   - Verify: `git diff dbt` shows comment lines only.
6. (last) Verify — `judgment` — R4.1–R4.3, expected values
   - `.agentic/gates`; query `dbt/ci.duckdb` for the game-line rows; then on the real
     season, `dbt build --select` the three tests.
   - Verify: every row of the expected values, recorded as a comment on #74. A CI
     warning that was not expected to go or stay, or a count that differs, is reported
     with its cause before the PR is opened.
