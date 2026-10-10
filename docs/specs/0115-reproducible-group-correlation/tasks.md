# A group's correlation is the same on every build — tasks

Issue: #115 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #115 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADR 0046.

1. Record the starting point — `judgment` — R2.3, expected values, open questions
   - On the real season at the base commit: the view's three rows to full precision; a
     `before` copy of the warehouse kept aside; the reordered-copy check on it (design,
     *The reordered-copy check*), expected to report the view as differing.
   - Query the real season for a repeated (`matchup_id`, `is_home`) within a group of
     `side_denominators`, and a repeated (`matchup_id`, `side`) within a group of
     `period_means` (R4.3). If either has one, stop and ask the owner.
   - Read the rules behind `denominator_parts` and say how many components a rate
     category's denominator has and whether their weights are whole numbers (design,
     *Open questions*). Report it to the owner; do not order that sum without a decision.
   - Verify: the rows, the check's output and both answers posted on #115.
2. The unit test, seen to fail — `impl` — R1.1, R1.2, R1.3
   - Add `category_wins_by_group_take_the_correlation_in_player_order` to
     `_rec_fantasy__models.yml`, with what it catches in its description; add
     `correlation` to the expected row of
     `category_wins_by_group_measure_the_slope_over_measured_pairs`: the ordered `corr`
     of its three measured pairs, read from DuckDB (1.0000000000000002 on 1.5.5), not 1.
   - Starting input (spiked): values 8.9, 2.0, 1.2, 1.2, 7.5 and wins 3.4, 3.9, 2.7, 2.5,
     2.7 for players 1 to 5, listed 5 to 1; player-order correlation 0.14953126241169692.
   - Verify: `dbt test --select rec_fantasy__category_wins_by_group --target ci` fails on
     the new test, on the last digit; the existing test may fail too if the unordered
     value differs from the pinned one, and passes after task 3. If no listing makes it fail on the unordered
     `corr`, stop and report: do not commit a test that cannot fail.
   - One unit test for each average of R4, in the YAML of its model: non-integer inputs
     listed in descending key order, the result pinned to the last digit of the
     key-order average. The same rule: seen to fail on the unordered `avg()`, or not
     committed and reported.
3. The model and its description — `impl` — R1.1, R1.4, R3.3
   - The `order by` and its comment; the `correlation` description in the YAML.
   - Verify: the unit tests of the view pass; `sqlfluff lint` clean if #116 has merged.
4. The two averages — `impl` — R4.1, R4.2
   - The `order by` and its comment in `int_fantasy__category_scales` and
     `int_fantasy__reported_matchup_margins`, as the design writes them.
   - Verify: both models' unit tests pass; `sqlfluff lint` clean if #116 has merged.
5. The rule in `AGENTS.md` — `impl` — R3.1, R3.2
   - The entry in the design, under *dbt gotchas* (accepted by the owner, 2026-10-10).
   - Verify: `git diff AGENTS.md` is that entry alone.
6. (last) Verify on the real season — `judgment` — R2.1, R2.2, R4.4, expected values
   - `.agentic/gates`. Build the real season twice into new files; compare each with the
     other exactly (`--strict-columns`), and one with the `before` copy; run the
     reordered-copy check on one of them; query the view.
   - Verify: every row of the expected values recorded as a comment on #115, with the
     commands. A relation other than this view that differs, or a correlation that
     differs from the expected one, is reported with its cause before the PR is opened.
