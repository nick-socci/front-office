# The replacement level for a start — tasks

Issue: #89 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. Progress and run evidence are recorded on #89.

The first commit of the build accepts ADR 0029 and notes on ADRs 0001 and 0009 that it
amends them.

1. Record the starting point — `judgment` — expected values
   - Copy `data/warehouse.duckdb` and, after a gates run, the CI warehouse.
   - Verify: posted on #89.
2. The start pool — `impl` — R1.1–R1.7, R4.1–R4.4
   - New and revised unit tests first, seen to fail; then the model and its header;
     then `int_fantasy__replacement_pool_is_at_most_n`.
   - Verify: CI build; real build of the model: the start level of the expected values,
     batting and relief rows identical to the starting point.
3. Headers of the value facts — `impl` — R2.1
   - Verify: `git diff` of the three facts is comments only.
4. The re-scoring model and its test — `impl` — R3.1–R3.9, R4.5
   - Unit tests first; then `rec_fantasy__category_wins_added`, its contract,
     `rec_fantasy__category_wins_by_group` and `values_track_rescored_category_wins`.
   - Verify: CI build; two real builds give identical rows; build time recorded.
5. (last) Verify against the real season — `judgment` — R5.1–R5.3, expected values
   - Full real build and `.agentic/gates`; every relation compared with the starting
     point; every row of the expected values.
   - Verify: posted on #89. Anything outside the stated values or tolerances: finish the
     other checks, then stop and take it to the owner (R5.3).
