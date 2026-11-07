# Where the daily run runs — tasks

Issue: #216 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #216 during the build, and this file is not edited to show it.

The build of this spec changes no pipeline code. It moves the landing zone's writer to the
chosen host, runs a spike there, and writes the records that follow from it. Tasks 2 to 4 assume ADR 0121 as recommended. If the owner chooses
another host, they apply to that host, with task 4's measurement replaced by that host's limits.

1. Record the NAS's model, CPU architecture, total and free memory, DSM version, free space on
   the volume that would hold the landing zone, and the schedule and free space of its backup
   job to the external drive — `judgment` (the owner) — R2.4, R3.2, R5.3
   - Verify: a comment on #216; free space at least 12 GB plus two seasons at about 8 GB (C9), on
     the volume and on the external drive.
2. Write a throwaway image definition for the spike, outside the repository (`data/spike216/`):
   Python 3.13, `uv sync --locked --group bigquery`, the repository at `main`, and Dagster as C8
   used it — `impl` — R6.1
   - Verify: the image builds for the NAS's architecture; `front-office --help` runs in it.
3. Move the writer: copy the laptop's landing zone to the NAS volume (`rsync --archive`, nothing
   fetching on either side), run `front-office repair --dry-run --deep` there, and from then on
   run no fetch on the laptop against production. Mount it into the container, with `.env` and a
   key for a service account created with ADR 0124's starting roles, both read-only. The owner
   creates the account — `judgment` (the owner, for the credentials) — R2.1, R5.1
   - Verify: the dry run moves nothing; the copy's capture count equals the laptop's
     (`LandingZone.iter_landed`); `docker image history` and the container's log hold neither
     cookie's value nor the key's `private_key_id`.
4. Run on the NAS by hand: Dagster's daemon and UI idle (C8's probe), then, beside them, one run:
   `backfill mlb`, `backfill espn`, `backfill idmap`, a real `upload` with the spike account, and
   `dbt build --target bq --selector bigquery --exclude-resource-type unit_test` into `_216`
   datasets (`dbt seed` and the functions first, as AGENTS.md says), also with the spike account.
   Then `compare_bigquery.py --suffix _216` against a DuckDB build on the laptop of a fresh pull.
   Name `FO_BQ_PROJECT` explicitly. Where the account is refused, add the narrowest role that
   lets the step run, and record it — `judgment` — R3.2, R4.1, R4.2, R5.2, R6.1, R6.2
   - Verify: one capture this run landed, found by its `file_path` in `raw.captures` and its
     endpoint's raw table, and its rows in the `_216` staging model that reads it. Peak PSS summed
     over the container, wall time per step and bytes billed, recorded on #216. Every relation
     exact. The account's final roles recorded. If the peak does not fit the NAS's free memory,
     stop: R6.2.
5. Once accepted, set ADR 0119's status to "amended by 0121"; reword AGENTS.md's rule 3 as ADR
   0124 gives it; update the README's roadmap and the milestone's description to the decided
   host and Dagster's role — `impl` — R3.1, R5.1
   - Verify: `.agentic/gates` (the ADR header tests).
6. Hand the requirements this spec sets but later issues carry out to those issues, as a comment
   on each: R3.1, R6.3 (measure again with the real definitions), C8's dagster-dbt failure and
   design-review F5 (the in-season steps) to #217; R1.2, R2.2, R5.1 to R5.3 to #218; R1.3 to
   #219 and #220; C16's bytes to #220 — `impl` — R1.2, R1.3, R2.2, R3.1, R5.1 to R5.3, R6.3
   - Verify: each issue's comment links this spec and names its requirements.
7. (last) Verify every acceptance criterion and expected value that this spec can check (R1.4,
   R2.3, R2.4, R3.2, R4, R6) against task 1's and task 4's records, and post the cost per service.
   The rest is checked where task 6 sent it — `judgment` — all
   - Verify: record the results as a comment on #216.
