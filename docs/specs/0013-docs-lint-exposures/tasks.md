# Docs site, SQL lint, exposures and the record — tasks

Issue: #13 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress and
run evidence are recorded on #13 during the build, and this file is not edited to show
them.

The first commit of the build accepts ADRs 0040 to 0043. If a SQL pull request is open
when the build starts, stop and say so: the reformat (task 7) would conflict with it.

1. Record the starting point — `judgment` — R2.4, R2.5, R5.5, expected values
   - Real season, at the base commit: `dbt build`, its result counts and warnings;
     `count(*)` of `raw.api_responses`; then copy `data/warehouse.duckdb` to
     `data/warehouse_before.duckdb`. Fixtures: the gates' counts.
   - Verify: posted on #13.
2. Enable GitHub Pages with "GitHub Actions" as the source — **the owner** — R1.1
   - Settings → Pages → Source: GitHub Actions; or
     `gh api -X POST repos/nick-socci/front-office/pages -f build_type=workflow`.
   - Must be done before the build's PR merges. An agent does not do this.
   - Verify: `gh api repos/nick-socci/front-office/pages -q .build_type` prints
     `workflow`.
3. Lint dependencies and configuration — `impl` — R2.2, R2.7
   - `sqlfluff` and `sqlfluff-templater-dbt` in the `dev` group at one version;
     `uv lock`; `.sqlfluff` as in design §1. Its own commit.
   - Verify: `uv run sqlfluff lint dbt/models dbt/tests` runs and reports the expected
     774 violations in 94 files, give or take the version.
4. Hand edit: rename the CTE `prior` — `impl` — R2.1, R2.3
   - In `int_fantasy__category_scales.sql` only, to `earlier_seasons`. Its own commit.
   - Verify: no parse error is reported; `dbt build --target ci --select
     int_fantasy__category_scales+` passes.
5. Rule triage — `judgment` — R2.2, R2.6, ADR 0041
   - Run `sqlfluff fix` in the working tree, uncommitted, and lint again. For each rule
     still reporting, in design §1's order: leave on, fix by hand, or turn off with its
     reason in `.sqlfluff`. Read the `RF04` and `CP02` hits one by one.
   - Stop condition: a rule that would need more than ten hand edits, or any edit that
     changes a relation, is turned off or taken to the owner; it is not obeyed.
   - Verify: the final rule list, with counts and reasons, posted on #13 before task 7.
6. Any further hand edits the triage calls for — `impl` — R2.3, R2.6
   - Its own commit, before or after the reformat as the edit requires; never in it.
   - Verify: `git show --stat` of the commit lists only the files the triage named.
7. The reformat — `impl` — R2.3, R2.9
   - `uv run sqlfluff fix dbt/models dbt/tests`, committed alone. Then, in the next
     commit, `.git-blame-ignore-revs` with that commit's hash and a one-line comment.
   - Verify: `git show --stat <hash>` lists only `.sql` files under `dbt/models` and
     `dbt/tests`; `uv run sqlfluff lint dbt/models dbt/tests` exits 0.
8. Prove the reformat changed nothing — `judgment` — R2.4, R2.5
   - `dbt build` on the real warehouse; `count(*)` of `raw.api_responses` equals task
     1's; `scripts/compare_warehouses.py data/warehouse_before.duckdb
     data/warehouse.duckdb --strict-columns`; the `information_schema.columns` query of design §1 on
     both files; the fixture build's counts.
   - Verify: exit 0, no difference, and equal counts, posted on #13. Any difference stops the
     build and goes to the owner.
9. Lint in the gates and CI — `impl` — R2.1, R2.8
   - The step in `.agentic/gates` and `ci.yml`, after `dbt deps`, before `dbt build`;
     the command in `AGENTS.md`.
   - Verify: `.agentic/gates` passes; a deliberate bad indent in a scratch edit fails
     it, and the edit is discarded.
10. The examples check, tests first — `impl` — R3.3, R3.4, R3.5, R3.6
    - `ingestion/tests/test_check_examples.py` with the cases of the test strategy,
      seen to fail; then `scripts/check_examples.py`.
    - Verify: `uv run pytest ingestion/tests/test_check_examples.py` passes.
11. The exposures — `impl` — R3.1, R3.2, R3.7
    - `dbt/models/marts/_exposures.yml` as in design §2; the gate step in
      `.agentic/gates` and `ci.yml`.
    - Verify: `uv run python scripts/check_examples.py --db dbt/ci.duckdb` passes;
      `dbt build --target ci --select +exposure:front_office_dashboard` and
      `+exposure:roster_day_query` pass.
12. *(Only if the owner chose R3.8.)* Three mart examples — `judgment` — R3.8, R5.8
    - What each shows is decided here and shown to the owner with its real-season
      output, which is not committed. Each gets its exposure.
    - Verify: task 11's commands, for the new files.
13. The site builder, tests first — `impl` — R1.3, R1.4
    - `ingestion/tests/test_build_docs_site.py` with the positive and four negative
      cases, seen to fail; then `scripts/build_docs_site.py`; `site/` in `.gitignore`.
    - Verify: the tests pass; on the fixture build the script passes and prints 56
      models, 1 source and the exposures.
14. The overview page — `judgment` — R1.5, R5.8
    - `dbt/models/overview.md`.
    - Verify: `dbt docs generate --target ci`, then `dbt docs serve`, and read the
      landing page and the lineage graph from source to exposures.
15. Generate, check and deploy in the gates and CI — `impl` — R1.1, R1.2, R1.6, R1.7
    - The steps and the `deploy-docs` job as in design §3, with the action versions
      checked; top-level `permissions: contents: read`; the same steps in
      `.agentic/gates`, without the upload.
    - Verify: `.agentic/gates` passes. On the PR: the `quality` job generates and
      checks the site, and `deploy-docs` is skipped.
16. Freshness: prove and document — `judgment` — R4.1 to R4.4
    - `dbt source freshness` on the real warehouse, against `max(fetched_at)` read
      directly; the source's comment rewritten.
    - Verify: the two ages agree to the minute; posted on #13. `git grep -n "source
      freshness" .agentic .github` finds nothing.
17. The README test, then the READMEs — `impl` for the test, `judgment` for the prose —
    R1.8, R4.4, R5.1 to R5.8
    - `ingestion/tests/test_readme.py`, which parses the table under `## The marts`,
      seen to fail; then `README.md` and
      `docs/README.md` as in design §5, every number from a run recorded on #13.
    - Verify: the test passes; each of R5.6's three stale statements is gone
      (`git grep -n "still pending\|100 pytest\|Thirty tests" README.md` finds nothing).
18. (last) Verify every acceptance criterion and expected value against real data —
    `judgment` — all
    - Every row of the expected-values table, re-read; `.agentic/gates`; the PR's CI
      run. After the owner merges: the `deploy-docs` run on `main`, the site's address
      loading, the lineage graph rendering, the overview reading as written.
    - Verify: record the queries and results as a comment on #13. The post-merge checks
      are the owner's or a follow-up comment; an agent does not merge.
