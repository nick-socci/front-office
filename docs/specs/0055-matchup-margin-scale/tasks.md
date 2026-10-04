# Total value scaled by the matchup margin — tasks

Issue: #55 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #55 during the build, and this file is not edited to show
them.

1. Snapshot today's facts — `judgment` — R2.5
   - Save `fct_player_category_value`, `fct_player_season_value` and
     `fct_transaction_impact` from the real warehouse to a local, gitignored file.
   - Verify: 9,860, 580 and 737 rows.
2. Build `int_fantasy__category_scales` — `impl` — R1.1–R1.5
   - Unit tests first: the rms and its symmetry under swapping sides, a null side value,
     the side denominator for a rate and a count, a zero-denominator side left out of it, a category with no matchups. Singular
     test that its categories are the scored categories.
   - Verify: 17 rows, 143 matchups each, scales and denominators as in the expected values.
3. Write the header of the scale model — `judgment` — R4.1
   - Definition, rate conversion, sample, sensitivity without the two long periods.
   - Verify: header numbers match a fresh query, recorded on #55.
4. Change `fo_standardised_value` and `fct_player_category_value` — `impl` — R2.1–R2.5
   - Unit tests first: a count, a rate, no played day, zero scale, null scale, null value.
     Restate existing unit tests against a mocked scale, saying in each why an expected
     value changed. Reword the fact's and the season fact's descriptions.
   - Verify: `dbt build --select fct_player_category_value fct_player_season_value`; 9,860
     and 580 rows.
5. Read the scales in `fct_transaction_impact` and replace the spread test — `impl` — R3.1, R3.2
   - Unit tests restated with their arithmetic. Replace
     `fct_transaction_impact_reads_the_season_facts_spread` with
     `value_facts_share_the_category_scales`.
   - Verify: 737 rows; the whole-season-add test passes on the real season; the four
     sums match the expected values; `.agentic/gates` green.
6. Record the supersession — `judgment` — R4.2
   - ADR 0003's status and index row; a dated amendment in spec 0011's design.md; a
     comment on #12 that its scalar is ADR 0010's.
   - Verify: the three agree.
7. Judge the numbers — `judgment` — R2, R3
   - Top and bottom 20, the pairs with 20 or more saves, the best and worst adds and
     drops. Anything absurd is a finding about the definition, not something to tune.
   - Verify: readout on #55; the owner signs off the eye test there.
8. Verify every acceptance criterion and expected value against real data — `judgment` — all
   - Includes the snapshot comparison of all 9,860 rows upstream of the standardisation.
   - Verify: record the queries and results as a comment on #55.
