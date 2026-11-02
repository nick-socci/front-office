# A float aggregate is computed in its stated order on BigQuery too — tasks

Issue: #139 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #139 during the build, and this file is not edited to show it.

1. Inventory the 39 calls (35 in models, 4 in singular tests): for each, the file and
   line, the expression, its type on DuckDB (from the compiled model, or `describe` of the
   output column), its order key, and why that key is unique within the group, or why ties
   change nothing. List any call whose expression is not a float (R1.6): its fix is a plain
   `sum` with an `order-exempt:` comment once the owner approves the list, and its model's
   DuckDB build is then compared with `main`'s (R1.6). — `judgment` —
   R1.6, design "Order keys"
   - Verify: the table posted on #139; 39 rows, matching C1's counts.
2. Mark ADR 0115 and 0116 `accepted` with the approval date, ADR 0046 `accepted, amended
   by [0115]`, and ADR 0053 `superseded by [0116]`. — `impl` — R5.2
   - Verify: `uv run pytest ingestion/tests/test_adr_headers.py`.
3. Unit tests for the folds' edges (R3.2), each with its expected value computed on
   DuckDB and stated in its description. On `int_fantasy__category_scales`'s
   `side_denominator`: a category whose only values are null (null), a null among three
   values (the mean of the other two), one value (that value). On
   `rec_fantasy__category_wins_by_group`'s `correlation`: a single pair (NaN), a zero
   variance in `total_value` (NaN), and a pair with a null side among four (the
   correlation of the other three, as if the fourth were absent). Fixtures in the forms AGENTS.md lists. If a NaN
   cannot be stated in an `expect` block that both warehouses accept, stop and report it
   rather than dropping the case. — `impl` — R3.2
   - Verify: the new tests pass on `ci` (`dbt test --target ci --select test_type:unit`).
     They pass on DuckDB before any change, because DuckDB already computes these.
4. `ingestion/tests/test_float_folds.py` (R3.3): a Python mirror of the two JavaScript
   bodies in the design, line for line, and DuckDB's `sum(x order by k)`,
   `avg(x order by k)` and `corr(y, x order by k)` over the same seeded random groups
   (sizes 1 to 500, about 10% nulls, magnitudes from 1e-6 to 1e6, both signs). Compared
   with `==`, NaN equal to NaN. — `impl` — R3.3
   - Verify: passes; and fails when the mirror's fold is reversed (checked once by hand,
     said in the test's docstring).
5. A pytest over `dbt/functions/*.js` (R3.4): no `'''`, no `{{`, `{%` or `{#`, beside the
   solver file's test. — `impl` — R3.4
   - Verify: passes; fails on a planted `'''` (checked once by hand).
6. `dbt/functions/sum_in_order.js`, `dbt/functions/corr_in_order.js` and their entries in
   `_functions.yml`, as the design gives them: enabled on BigQuery only, `volatility:
   deterministic`, the arguments and return types stated. `corr_in_order.js` copies the
   statement order of `probes/m2_corr.py`'s `duck_corr`, without its zero-deviation
   special case. — `impl` — R1.1, R1.3, R1.5
   - Verify: tasks 4 and 5 pass; `dbt parse` on `ci` and `bq`.
7. The BigQuery forms of `fo_sum_in_order`, `fo_avg_in_order` and `fo_corr_in_order` in
   `dbt/macros/portable.sql`, as the design's table gives them, and the comment above them
   rewritten to say what each form computes and why the two warehouses agree (ADR 0115).
   — `impl` — R1.1, R1.2, R1.3, R5.1
   - Verify: `dbt compile --target bq --select int_fantasy__category_scales` shows the
     function call; `.agentic/gates` green.
8. DuckDB unchanged (R1.4): `dbt compile` on `ci` and on `dev`, on `main` and on the
   branch, into separate target paths; `diff -r` of the compiled models and tests. —
   `impl` — R1.4
   - Verify: no difference outside the new unit tests of task 3 and any call changed
     under R1.6; recorded on #139.
9. `compare_bigquery.py` exact (R2): remove the tolerance path, keep the rest, add the
   per-column report of R2.3, rewrite the docstring (R5.1). Extend
   `test_compare_bigquery.py`: a relation whose float differs in the last digit fails,
   and the report names the column; one whose float values are swapped between two rows
   fails and names it too; equal ones pass. — `impl` — R2.1, R2.2, R2.3, R5.1
   - Verify: `uv run pytest ingestion/tests/test_compare_bigquery.py`; gates green.
10. The record (R5.1, R5.3): AGENTS.md (the line on the four float tests of #139 goes;
    the float-aggregate gotcha says BigQuery states the order too), and any README or
    docs-site page that says floats are held to a tolerance or that BigQuery does not
    repeat itself (`grep -rniE 'tolerance|repeat itself|1e-9' README.md docs/ --include=*.md`,
    leaving ADRs and earlier specs as they are). — `impl` — R5.1, R5.3
    - Verify: the grep shows no current claim of a tolerance outside ADRs and specs.
11. BigQuery, suffixed `_139`, following AGENTS.md's unit-test commands: `dbt seed`, the
    functions, the `--empty` run of the selector, the data tests over it, and the unit
    tests. Record each step's result and bytes billed on #139. An `INT64` call that fails
    here goes back to task 1's list and to the owner. — `judgment` — R1.5, R1.6, R3.1
    - Verify: every unit test passes, the four of #139 and task 3's included; 0 errors.
12. (last) The real season (R4, expected values). Build the selector populated into
    `_139` from the captures the real DuckDB warehouse was built from, as #137 did
    (`dbt build --target bq --selector bigquery --exclude-resource-type unit_test`, about
    56 GB, C12). Compare it with that DuckDB build: `compare_bigquery.py --suffix _139`.
    Copy the 13 models' tables and their descendants' (copy jobs bill nothing), rebuild
    `--select` those 13 models and everything downstream into `_139`, and compare with
    the copies, exactly. Record the bytes billed per model beside a dry run of `main`'s
    compiled SQL for each of the 13 models (free), explaining any that bills more, and the
    13 models' summed time against `main`'s. If any float
    column differs, trace it (R4.3) and take it to the owner before anything else. —
    `judgment` — R4.1, R4.2, R4.3, all expected values
    - Verify: the queries, counts and timings recorded as a comment on #139.
