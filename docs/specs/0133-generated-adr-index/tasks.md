# The ADR index is generated onto the docs site — tasks

Issue: #133 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #133 during the build, and this file is not edited to show it.

1. Record the starting point: save `git show HEAD:docs/adr/README.md` outside the tree,
   and count the ADR files and their status words — `judgment` — expected values
   - Verify: the counts are posted on #133; they are the numbers the last task compares.
2. Write `ingestion/tests/test_adr_headers.py`: the made-up-directory cases for R2.1 to
   R2.4 (repeated header lines and each status form among them), the missing and empty
   directory of R1.10, and the README case for R3.2 — `impl` — R1.10, R2.1, R2.2, R2.3,
   R2.4, R3.2
   - Verify: `uv run pytest ingestion/tests/test_adr_headers.py` fails on import (no
     `adr_index` yet).
3. Write `scripts/adr_index.py`: `read_adr`, `read_all`, `AdrError` — `impl` — R1.10,
   R2.1, R2.2, R2.3, R2.4
   - Verify: the R2 cases pass; `read_all("docs/adr")` raises nothing on the real files,
     with no ADR file edited; the README case still fails (the table is still there).
4. Add the rendering cases to `ingestion/tests/test_adr_headers.py`, then `render` in
   `scripts/adr_index.py` — `impl` — R1.2, R1.3, R1.4, R1.5
   - Verify: the cases of the test strategy for R1.2 to R1.5 pass.
5. Change the site tests in `ingestion/tests/test_build_docs_site.py` to four files and
   add the negatives, then change `scripts/build_docs_site.py`: `GENERATED`,
   `--adr-dir`, the `AdrError` path, the four-name check and the GUID check on
   `decisions.html` — `impl` — R1.1, R1.6, R1.7, R1.8, R1.10
   - Verify: `uv run pytest ingestion/tests/test_build_docs_site.py` passes; the old
     "exactly three files" case is gone, not skipped.
6. Rewrite `docs/adr/README.md` without the table; add the links in `README.md`,
   `docs/README.md` and `dbt/models/overview.md`; correct `README.md`'s sentence that the
   site is assembled from three files; add the line to `AGENTS.md`; add
   "amended by 0062" to ADR 0042's `Status` line — `impl` — R1.9, R3.1, R3.3
   - Verify: the R3.2 case passes; `test_readme.py` still passes.
7. Decide how the overview links the page: build the fixture site with `.agentic/gates`
   and open `site/index.html` and `site/decisions.html` in a browser — `judgment` — R1.9
   - Verify: the link in the overview opens the page; if a relative link does not
     resolve inside dbt's viewer, it is the site's full address, and design.md gets a
     dated *Amendments* entry saying so.
8. (last) Verify every acceptance criterion and expected value — `judgment` — all
   - Verify: `.agentic/gates` is green; `site/` holds exactly four files; the page's row
     count and status counts equal task 1's; the generated rows compared with task 1's
     saved table differ only in the titles and statuses the requirements name, plus any
     rows merged since; each new test was seen to fail. Post the comparison and the
     results as a comment on #133.
