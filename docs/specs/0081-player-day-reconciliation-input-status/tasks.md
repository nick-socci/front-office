# A player-day difference says whether its inputs were verified — tasks

Issue: #81 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #81 during the build, and this file is not edited to show
them.

Built after #93 merges. The first commit of the build accepts ADR 0032.

1. Record the starting point — `judgment` — expected values
   - Confirm #93 is merged. On the real season, copy the table as it is to a scratch
     database outside the repo; record its 22 rows by `input_status`. In CI, the row
     count and the build's counts.
   - Verify: the "now" column of the expected values, posted on #81.
2. The unit test and the column tests — `impl` — R4.1–R4.3
   - Written first and seen to fail: the eight cases, the two columns' tests, the
     uniqueness test.
   - Verify: `dbt build --target ci --select rec_espn__player_day_differences` fails on
     the missing columns.
3. The model — `impl` — R1.1–R1.4, R2.1–R2.3, R4.4
   - The two columns, the header comment, the YAML description.
   - Verify: the same command passes; `git diff` shows no change to the `where` clause
     or to any existing column.
4. The residuals view and its test — `impl` — R3.1–R3.5
   - The unit test first, six cases, seen to fail; then the view, its YAML (grain
     uniqueness, `problem` accepted values) and the singular test.
   - Verify: `dbt build --target ci --select rec_espn__player_day_residuals+` passes;
     then on the real season `dbt build --select rec_espn__player_day_differences+`.
5. (last) Verify — `judgment` — expected values
   - `.agentic/gates`. On the real season: the `except` comparison against the copy
     from task 1; the counts by status; the view's 22 rows with no `problem`.
   - Verify: every row of the expected values, recorded as a comment on #81. A count
     that differs is reported with its cause before the PR is opened.
