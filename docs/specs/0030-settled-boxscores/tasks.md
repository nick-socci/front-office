# Settled boxscores — tasks

Issue: #30 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #30 during the build, and this file is not edited to show
them.

1. Record the starting point — `judgment` — expected values
   - On the real landing zone: played games, boxscore captures by run, and the audit's
     `mlb` lines as they are before the change. Post them on #30.
   - Verify: matches the first two rows of the expected values.
2. Each game gets a last scheduled start — `impl` — R1.1, R1.3
   - pytest first: postponed-then-played, resumed (two played entries), a played game
     with a later session still scheduled, an entry with no `gameDate`, one that does
     not parse, and a resumed game whose later entry is the unreadable one; the existing
     schedule tests pass unchanged.
   - Then `ScheduledGame.last_start` and the pass in `games_from_landed_schedule`.
   - Verify: `uv run pytest ingestion/tests/test_boxscore.py`; ruff; mypy.
3. `parse_stamp`, `first_final` and `is_settled` — `impl` — R1.2, R1.4, R2.1
   - pytest first, on plain instants: no captures; one capture; 7 days less a second and
     exactly 7 days; captures before the last start ignored; `last_start` of `None`.
   - Verify: `uv run pytest ingestion/tests/test_boxscore.py`.
4. The fetch path uses the capture rule — `impl` — R1.4, R2.2–R2.7, R4.1, R4.2
   - pytest first: delete the four boxscore tests named in R4.1 and add the scenario
     tests from design.md (day 0 only then day 8; a missed week; an old official date
     captured late; a resumed game captured during its suspension; `--refresh`; another
     season's capture; a settled game reopened by a newer schedule; the clock frozen far
     in the future). Re-point the three boxscore
     tests in `test_landing_check.py` at the new signature, keeping what each is for and
     "boxscore payload reads raise".
   - Then the stamp pass in `backfill_boxscores`, the pure `needs_fetch`, and the
     removal of `today` from both.
   - Verify: `uv run pytest ingestion/tests`; ruff; mypy.
5. The audit calls the same functions — `impl` — R3.1–R3.5, R4.1
   - pytest first: replace the two audit tests named in R4.1 with tests of settled,
     window closed, window open, captures only before the last start, a resumed game
     judged by the guard, and `--today` on the closing day and the day before.
   - Then `check_mlb` on `first_final` and `is_settled`, `as_of` in place of `today`
     through `run_audit` and the command, and the two reworded findings.
   - Verify: `uv run pytest ingestion/tests/test_audit.py ingestion/tests/test_cli_landing.py`.
6. Describe it — `impl` — goals
   - The module docstrings of `mlb/boxscore.py` and `audit.py`; the README where it
     describes the settle window. No status tables.
   - Verify: `.agentic/gates`.
7. (last) Verify against the real season, reading only — `judgment` — all
   - The new functions over the real landing zone: 2,429 played, 2,402 settled, 27 not
     (official dates 2026-09-26 and 2026-09-27), 0 captures before a last scheduled
     start, game 824912 settled; the fetch decision says 27 of 2,429; the audit warns of
     those 27 and names the command; `git diff --stat main` shows nothing under `dbt/`
     or `fixtures/`.
   - No request is made to MLB. A live `front-office backfill mlb --season 2026` is the
     owner's to run; expected `boxscores: fetched=27 skipped=2402 failed=0`, after which
     the audit's warning is gone.
   - Verify: commands and results posted as a comment on #30.
