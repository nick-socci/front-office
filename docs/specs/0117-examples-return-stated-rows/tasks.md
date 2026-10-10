# An example returns the rows it should on the fixtures — tasks

Issue: #117 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #117 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADRs 0048 and 0049, and marks ADR 0045's row in the
index as amended by 0048.

1. Record the starting point, and settle the command-line question — `judgment` — R2.2,
   expected values, open questions
   - On the real season at the base commit: the roster example's rows, kept aside for the
     comparison of task 6.
   - On the fixture warehouse the gates build at the base commit: the four row counts,
     and for team 11 on 2026-04-29 the 18 rows and the two value counts. If any differs
     from the expected values, stop and report: the fixtures have moved since the spec.
   - With the DuckDB command-line client (ask the owner where it is installed if it is
     not on the `PATH`): pipe a file that reads an unset variable with the `coalesce`
     form, and one preceded by `set variable`. Record the client's version and which way
     of setting a variable the header will show. If an unset variable is not NULL there,
     stop: ADR 0049 does not hold.
   - Verify: the numbers, the client's version and the chosen wording posted on #117.
2. The tests of the expectations, seen to fail — `impl` — R1.1 to R1.5, R2.3, R2.4, R3.1,
   R3.2
   - Every row of the design's test strategy that names a pytest, except the two on the
     committed files (task 5), in `ingestion/tests/test_check_examples.py`, each with
     what it catches in its docstring.
   - Verify: `uv run pytest ingestion/tests/test_check_examples.py` fails on the new
     tests and passes on the old ones. A new test that passes before task 3 is reported,
     not committed.
3. The gate — `impl` — R1.2 to R1.5, R2.3, R2.4, R3.1, R3.2
   - `load_expectations`, `check_expectations`, the `--expectations` argument and the
     changes to `run_examples`, as the design writes them. The module docstring says what
     the gate now holds.
   - Verify: the tests of task 2 pass; `uv run ruff check`, `uv run ruff format --check`
     and `uv run mypy` are clean.
4. The roster example reads variables — `impl` — R2.1, R2.5
   - The `params` block and the header, as the design writes them, with the wording task
     1 chose.
   - Verify: `uv run python scripts/check_examples.py --db dbt/ci.duckdb` still reports
     that the example matches its exposure. It fails for the missing expectations file
     until task 5, which is expected.
5. The expectations file and the tests on the committed files — `impl` — R1.1, R2.1,
   R3.3, R4.2
   - `docs/examples/expected_on_fixtures.yml` as the design writes it, with the numbers
     task 1 confirmed. The two tests of the test strategy that read the committed files.
   - Verify: `uv run python scripts/check_examples.py --db dbt/ci.duckdb` exits 0 and
     prints 12, 4, 15 and 18 rows; `uv run pytest ingestion/tests/test_check_examples.py`
     passes.
6. The breaks, by hand — `judgment` — R1.2, R3.1, expected values
   - On a scratch copy of the examples directory (`--examples-dir`), never on the
     committed file: remove the join on `team_id`; remove the join on `scoring_date`;
     join batting to the day five days earlier; remove the join on `league_id`.
   - Verify: the gate's output for each, posted on #117. The first three fail with the
     numbers of the expected values; the fourth passes, and is recorded as the accepted
     gap.
7. `AGENTS.md` — `impl` — R4.1
   - The `_exposures.yml` entry of *Project shape* says the gate also holds each example
     to the counts stated in `docs/examples/expected_on_fixtures.yml`.
   - Verify: `git diff AGENTS.md` is that entry alone.
8. (last) Verify on the real season — `judgment` — R2.2, expected values, all
   - `.agentic/gates`. On the real season: the roster example as committed, compared row
     for row with the rows kept in task 1; the three mart examples' counts.
   - `git diff --stat origin/main` shows nothing under `fixtures/`, `.agentic/` or
     `.github/`.
   - Verify: every row of the expected values recorded as a comment on #117, with the
     commands.
