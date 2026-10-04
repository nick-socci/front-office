# Pitcher replacement level by kind of outing — tasks

Issue: #52 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #52 during the build, and this file is not edited to show
them.

1. Snapshot today's values and find every reader — `judgment` — R2.5, R4.2
   - Before any change, save `fct_player_category_value`, `fct_player_season_value` and
     `fct_transaction_impact` from the real warehouse to a local, gitignored file. Grep for readers of
     `replacement_group`, `pitcher_slot_replacement_group` and the `SP`/`RP` level keys;
     report any outside the four models and their tests.
   - Verify: snapshot holds 9,860, 580 and 737 rows; the reader list is posted on #52.
2. Correct the eligibility documentation — `impl` — R5.1
   - Rewrite the header of `stg_espn__roster_entry_slots` and its YAML description from
     design.md. No SQL change.
   - Verify: `dbt build --select stg_espn__roster_entry_slots` unchanged in rows (298,001).
3. Add `fo_pitching_day_kind` and re-key the replacement model — `impl` — R1.1–R1.6, R4.1
   - Unit tests first: classification by outing (including a day with a start and a
     relief appearance), ranking and tie-break, a pool member's
     off-kind day excluded, the empty `relief` pool. Re-key the existing unit tests and
     the two pool singular tests to `day_kind`.
   - Verify: on the real season the three pools match the expected values (306 and 833
     days; 4,584 and 2,334 outs; batting 1,690 days, AVG .2416).
4. Write the header of the replacement model — `judgment` — R1.7
   - Re-measure N/2 and 2N; state definition, bias and sensitivity.
   - Verify: header numbers match a fresh query, recorded on #52.
5. Value pitching categories by kind in `fct_player_category_value` — `impl` — R2.1–R2.4, R4.2
   - Unit tests first: the mixed pair, the null level, identical days with different
     default positions, a hitter-only pair keeping its pitching rows. Build the output
     from the pair × category spine. Rewrite `fct_player_season_value_day_counts_hold`
     to drop its `replacement_group` assertion and keep the played-day reconciliation. Rewrite existing unit tests to the new keys, stating in each
     description why any expected value changed. Remove `replacement_group` from the
     model and YAML. Re-key the "pool is worth zero" test.
   - Verify: `dbt build --select fct_player_category_value fct_player_season_value`; 9,860
     and 580 rows.
6. Value windows by kind in `fct_transaction_impact` — `impl` — R3.1–R3.3
   - Unit tests first: an add and a drop each holding both kinds.
   - Verify: 737 rows; `…an_add_covering_a_pair_reproduces_the_season_fact` passes on the
     real season; the four sums of `total_value` match the expected values.
7. Remove `dim_players.pitcher_slot_replacement_group` — `impl` — R4.2, R4.3
   - Model, YAML, its unit test, and every unit-test input row that names it.
   - Verify: `dbt build --select dim_players+`; 498 rows; `.agentic/gates` green.
8. Judge the numbers — `judgment` — R2, R3
   - Top and bottom 20 by `total_value`, every pair with 20 or more saves, and the best
     and worst adds and drops of pitchers. Do relievers pass the eye test? Do starters
     taking 15 of the top 20 pass it? Anything absurd is a finding about the definition,
     not something to tune away.
   - Verify: observations recorded on #52; the owner signs off the eye test there.
9. Accept the ADRs' consequences in the record — `judgment` — all
   - ADR 0001's status and index row say which part 0008 and 0009 supersede. Add a dated
     note to spec 0011's design.md *Amendments* pointing here for the pitcher groups and
     `pitcher_slot_replacement_group`.
   - Verify: `docs/adr/README.md` and the three ADRs agree.
10. Verify every acceptance criterion and expected value against real data — `judgment` — all
    - Includes the snapshot comparison: 5,220 batting rows identical, 260 of 261 hitter
      pairs unchanged.
    - Verify: record the queries and results as a comment on #52.
