# Where the daily run runs — tasks

Issue: #216 · Kind: `impl` = mechanical, delegable · `judgment` = lead agent or person

Ordered. Tests before the code they test. This is the plan, not the tracker: progress is
recorded on #216 during the build, and this file is not edited to show it.

The build of this spec changes no pipeline code. It runs a spike on a host, and writes the
records that follow from it. **Amended 2026-11-07 (design.md, Amendments):** task 1 found the NAS
too small (R6.2 fired), and the production host is now to be a home server not yet bought. Tasks
2 to 4 are therefore a *pre-spike* on a second Oracle Always Free A1 VM, with no league data on
it. The production spike (R6.1 as written: the writer moved, ESPN fetched, a real upload) is
repeated on the home server when it exists, and tasks 5 to 7 wait for it.

1. Record the NAS's model, CPU architecture, total and free memory, DSM version, free space on
   the volume that would hold the landing zone, and the schedule and free space of its backup
   job to the external drive — `judgment` (the owner) — R2.4, R3.2, R5.3
   - Verify: a comment on #216; free space at least 12 GB plus two seasons at about 8 GB (C9), on
     the volume and on the external drive.
2. Write a throwaway image definition for the spike, outside the repository (`data/spike216/`):
   Python 3.13, `uv sync --locked --group bigquery`, the repository at `main`, and Dagster as C8
   used it. Build it for `linux/amd64` and `linux/arm64` — `impl` — R6.1, R6.4
   - Verify: both builds succeed (`docker buildx build --platform linux/amd64,linux/arm64`, or
     one native build on each machine); in each, `front-office --help` runs, and importing
     scipy, numpy, duckdb and the `fo_duckdb_functions` plugin succeeds. A failure on either
     architecture is recorded with its error.
3. Provision the spike VM: a second Always Free A1 VM, apart from `hermes` (2 OCPU, 12 GB, the
   remaining allowance; `launch-a1.sh` retries for capacity). Key-only SSH, no ingress but SSH
   from the owner's address, Dagster's UI reached through an SSH tunnel. The owner creates a
   service account with ADR 0124's starting roles and puts its key on the VM, mode 0400 for the
   run's user. **No ESPN cookies, no copy of the laptop's landing zone, and no ESPN capture is
   ever on the VM** (one owner-approved exception, 2026-11-10: design.md, Amendments): its landing zone starts empty — `judgment` (the owner, for the VM and the
   credentials) — R5.1, R6.4
   - Verify: `ss -tlnp` shows no listener but sshd; no `.env` and no `espn/` directory under the
     VM's landing zone after task 4; the image history and the run's log hold neither the key's
     `private_key_id` nor a cookie name.
4. Run on the VM by hand: Dagster's daemon and UI idle (C8's probe), then, beside them:
   `backfill mlb --season 2026 --limit 200`, `backfill idmap`, `upload --dry-run` (local checks
   only: with `--project` it refuses this landing zone by design, R2.1) against that landing zone, and `dbt build --target bq --selector bigquery
   --exclude-resource-type unit_test` into `_216` datasets (`dbt seed` and the functions first,
   as AGENTS.md says) with the spike account. **No real upload**: `upload` appends to the shared
   raw dataset, so a second landing zone would add captures the laptop's copy lacks and make
   `compare_bigquery.py` differ for a reason that is not the build. The build reads production
   raw as the laptop's upload left it. Then `compare_bigquery.py --suffix _216` against the
   laptop's DuckDB build of the same landing zone. Name `FO_BQ_PROJECT` explicitly. Where the
   account is refused, add the narrowest role that lets the step run, and record it. Delete the
   key and the VM's account afterwards unless the owner keeps the VM — `judgment` — R3.2, R4.1,
   R4.2, R5.2, R6.2, R6.4
   - Verify: peak PSS summed over the container (daemon, UI and run), wall time per step and
     bytes billed (from `run_results.json`), recorded on #216, and C8 repeated with the real
     manifest's failure recorded (R6.3). Every relation exact. `upload --dry-run` without `--project`
     exits 0; with `--project` it refuses this landing zone and sends nothing (R2.1). The account's final roles recorded. The result is
     labelled arm64, and says what it does not show: a real upload, a landed capture in raw, the
     writer moved, ESPN, the NAS backup, and the home server's own memory.
5. (Waits for the home server's host ADR.) Once accepted, set ADR 0119's status to "amended by 0121"; reword AGENTS.md's rule 3 as ADR
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
