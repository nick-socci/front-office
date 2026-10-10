# The register of known differences names its league and season — tasks

Issue: #99 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #99 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADRs 0040 and 0041. If the owner declines ADR 0041,
task 5 writes the two joins in the test files instead and R5.3 is dropped.

1. Record the starting point — `judgment` — expected values
   - On the real season, copy `rec_espn__matchup_stat_differences` and
     `rec_espn__player_day_residuals` as they are to a scratch database outside the repo.
     Record the status counts, the CI build's `PASS`/`WARN` line on the current `main`,
     and the CI warning's row count.
   - Verify: the "now" column of the expected values, posted on #99; any that differs is
     reported before going on.
2. The seed and its YAML — `impl` — R1.1–R1.4, R6.1
   - The two leading columns on all 31 rows; `column_types`; `not_null` on both; the
     five-column uniqueness test; the description. The models still join on three
     columns at this point, which works: the new columns are extra.
   - Verify: `dbt seed --full-refresh --select espn_reconciliation_residuals` then
     `dbt build --select espn_reconciliation_residuals+` on the real season passes with
     31 `registered`; `git diff --word-diff` of the CSV shows only the two fields added
     per row.
3. The unit tests of the joins — `impl` — R5.1, R5.2, R5.4
   - Add `league_id` and `season` to the register rows of the two existing unit tests.
     Write the two new ones; remove
     `player_day_residuals_refuse_a_register_that_cannot_tell_seasons_apart`.
   - Verify: `dbt build --target ci --select rec_espn__matchup_stat_differences
     rec_espn__player_day_residuals` fails on the two new tests and on nothing else, for
     the reasons the design gives.
4. The joins, and the end of `ambiguous_register` — `impl` — R2.1–R2.4, R3.1–R3.3, R6.3
   - The two joins of `rec_espn__matchup_stat_differences`; the join, the `problem`
     column, the header and the YAML of `rec_espn__player_day_residuals`; the header of
     `rec_espn__player_day_differences_are_registered`.
   - Verify: the same command passes; `git grep -c ambiguous_register -- dbt` returns
     nothing; `git diff` shows no change to a select list.
5. The register view and the two tests — `impl` — R4.1–R4.5, R5.3, R6.3
   - The unit test first, seven cases, seen to fail on the missing model; then the view,
     its YAML (uniqueness, accepted values, description), and the two singular tests
     rewritten to select from it.
   - Verify: `dbt build --target ci --select rec_espn__register_rows+` passes with the
     warning at 31 rows and the view empty; on the real season the same selection passes with no warning.
6. `AGENTS.md` — `impl` — R6.2
   - The `dbt/seeds/` line, in the wording of the design.
   - Verify: `git diff AGENTS.md` shows that line alone.
7. (last) Verify — `judgment` — all
   - `.agentic/gates`. On the real season: `dbt build --select
     espn_reconciliation_residuals+`; the `except` comparisons against the copies of
     task 1; the status counts; the view's 31 rows. Then the probe of the design's test
     strategy: two uncommitted seed rows, a CI build that must fail on one and warn on
     the other, the seed restored.
   - Verify: every row of the expected values, recorded as a comment on #99. A count
     that differs is reported with its cause before the PR is opened.
