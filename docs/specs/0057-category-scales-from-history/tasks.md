# Category scales from the league's earlier seasons — tasks

Issue: #57 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #57 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADR 0027 and notes on ADR 0010 that 0027 amends it.

1. Record the starting point — `judgment` — expected values
   - Copy `data/warehouse.duckdb` under its own file name; copy the CI warehouse after a
     gates run; record the real and CI counts and warnings, and the 2026 scales.
   - Verify: posted on #57.
2. The bridge as a macro — `impl` — R1.3
   - Move the component-to-reported-stat bridge of
     `rec_espn__matchup_stat_differences` into a macro and use it there.
   - Verify: that model's rows are identical to the starting point, real and CI.
3. The reported margins — `impl` — R1.1–R1.6, R4.1
   - Unit tests first, seen to fail; then `int_fantasy__reported_matchup_margins` with
     its contract and header.
   - Verify: CI build; real build of the model: 143 to 155 matchups per played season,
     none for 2020, and AVG's denominators null in 2018 only.
4. The reported scales — `impl` — R2.1–R2.4, R4.2, R4.4
   - Unit tests and the row-per-category singular test first; then
     `int_fantasy__reported_category_scales`.
   - Verify: the *Matchups measured* table of requirements.md, and the "Reported, 2026"
     column of the scales table.
5. The scale in use — `impl` — R3.1–R3.7, R4.3, R4.4, R4.5
   - The new unit tests and singular tests first, seen to fail; the existing unit tests
     of `int_fantasy__category_scales` given an empty earlier history. Then the model,
     its two new columns in the contract, and the variable in `dbt_project.yml`.
   - Verify: CI build passes; in CI every scale is `current_season` and the value facts
     are identical to the starting point.
6. Headers and the isolation check's docstring — `impl` — R3.8
   - Rewrite the header of `int_fantasy__category_scales` and the scale paragraphs of
     the three value facts' headers; say in `scripts/check_tenant_isolation.py` what the
     check establishes now that a league-season reads its league's earlier seasons.
   - Verify: `git diff` of the three facts is comments only.
7. (last) Verify against the real seasons — `judgment` — R5.1–R5.3, expected values
   - A full real build and `.agentic/gates`. Compare every relation with the starting
     point; compute every row of the expected values.
   - Verify: posted on #57. A scale, a count or a ranking number that differs from
     requirements.md: stop and take it to the owner with both numbers.
