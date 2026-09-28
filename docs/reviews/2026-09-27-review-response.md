# Response to the 2026-09-27 code review

Response to [`2026-09-27-code-review.md`](2026-09-27-code-review.md). It records where the
implementing session agrees, where it proposes a different order, and the concrete fix
proposed for each finding. Nothing here is implemented yet. The aim is agreement on
**sequence** and **fix design** before work starts.

## Summary

- R1–R7 were checked against the code at `8484d06`. All seven hold as described.
- **The disagreement is about order.** The review puts all ingestion-lifecycle work
  (R1, R3, R4, R2) ahead of milestone 9. R1, R3 and R4 only bite under *daily operation*,
  and R2 only under a *second league or season*. Neither situation exists before the 2027
  season or sub-project 3's scheduler. The 2026 fantasy season is over and its data has
  landed. The proposal is to fix what milestone 9 depends on, build milestone 9, then
  harden ingestion before either trigger arrives.
- The one item that can lose data is **step 0**, and the review correctly changes how it
  must be run (`--refresh` on the Oct 5 pass).

## Proposed sequence

| Order | Work | Why now | Gate |
|---|---|---|---|
| 0 | Step 0: MLB backfill after 2026-09-27; `backfill mlb --season 2026 --refresh` on or after 2026-10-05; NAS backup | Time-bound; waiting loses data | 2,430 games landed; refresh run and backup recorded in `docs/README.md` with dates and counts |
| 1 | R5, R7, R6 | Milestone 9 is a reconciliation; its strongest existing check currently cannot fail | Mutation demos below fail as expected; auth expiry stops after one request |
| 2 | Intermediate dbt unit tests | Fixtures have zero doubleheaders and zero two-way player-days, and milestone 9's sums depend on both | Unit tests listed under "Intermediate tests" pass |
| 3 | Milestone 9 | — | As in design 02, plus the review's "missing ≠ zero" diagnostics |
| 4 | R2 | Must land **before any 2027 data**: `fo_espn_latest` would otherwise hide 2026 | Two leagues × two seasons fixture, including identical timestamps, builds clean |
| 5 | R1, R3, R4 (general fix) | Must land before scheduled daily ingestion (sub-project 3) or 2027 opening day, whichever is first | Transition and fault-injection tests below |
| 6 | Performance and portability | As the review says: only after correctness | As the review says |

If the reviewer thinks R2 is cheap enough to fold into step 1, that is acceptable. The
constraint is only that it precedes 2027 data.

## Per-finding response and proposed fix

### R1 — roster frozen before final state · agree · defer to order 5

Verified: `needs_fetch` (`espn/rosters.py:50`) returns false when *any* payload exists
and `period < latestScoringPeriod`. Offseason backfills are safe because every capture
was taken after its period closed. Daily runs are not.

Proposed fix:
- Record the league status at capture in the sidecar: `source_status: {latest_scoring_period, final_scoring_period}`.
- A period is **settled** iff some *committed* capture (see R3) has
  `source_status.latest_scoring_period > period`, or the capture was taken after the
  final period ended.
- Legacy captures have no `source_status`. Treat them as settled only if `fetched_at` is
  after the league's final period end date. Otherwise refetch them once. All 2026 captures
  should qualify, and this needs checking against the sidecars rather than assuming it.
- Tests: active → closed → repeated-closed runs. A scheduler outage spanning three
  periods. Legacy sidecar in both directions.
- Replace `test_roster_is_skipped_once_its_period_is_over`. It asserts the unsafe rule.

### R2 — league/season identity lost · agree · order 4, hard deadline before 2027 data

Verified: `request_key` is params-only (`landing.py:38`). The raw primary key is
`(source, endpoint, request_key, fetched_at)`. `fo_espn_latest` partitions only by an
optional extra param, so without one it takes the single newest response globally.

Proposed fix:
- Add `partitions` (JSON) and `url` to `raw.api_responses`, since the sidecar already holds them.
- Include the URL path in the request identity: key on `(source, endpoint, url, request_key, fetched_at)`.
- Migrate by rebuilding the raw table from the landing zone. It is a derived store by
  design, so no in-place migration is needed.
- `fo_espn_latest` partitions by `league_id, season` from partitions, plus the extra
  partition when present.
- Expose `league_id` and `season` in `stg_espn__transactions`. Generate
  `stg_espn__scoring_periods` per league from that league's own final period.
- Audit uniqueness and relationship tests for full compound keys.

### R3 — payload/sidecar orphan · agree · order 5

Verified: `LandingZone.write` renames the payload, then the sidecar. The `_has_landed`
helpers in both sources count any non-sidecar `.json` as landed.

Proposed fix:
- The sidecar is the **commit marker**. Rename the payload first and the sidecar last. A
  capture exists only when both are present.
- `has_landed` and both `_has_landed` helpers go through one shared
  `LandingZone.committed_captures(...)`. This is the centralization the review suggests.
- On each run, orphan payloads (no sidecar) are logged and moved to `_quarantine/`, so
  the entity counts as not landed and is refetched.
- Same-second rewrite: open the final path exclusively (`os.link` or `O_EXCL`) and fail
  loudly on collision. Do not silently overwrite. Sub-second precision in `fetched_at`
  is the alternative. **Reviewer's preference?**
- Tests: fault injection at each rename, then recovery on the next run.

### R4 — settle window can be skipped · agree · operational workaround now, fix at order 5

Verified: `mlb/boxscore.py:104` compares only `today - official_date` to the window.

- **Now:** step 0 uses `--refresh` on the Oct 5 pass. This is already in the amended docs.
- **Fix:** a game is settled iff a committed capture has
  `fetched_at >= official_date + settle_window`. Otherwise refetch, regardless of today's
  age. This reuses R3's capture discovery.
- Suspended or resumed games: use the schedule's resumed date where the schedule API
  provides it, and document the limitation otherwise.
- Tests: missed week of runs. A game captured only on day 0. A resumed game with an old
  `official_date`.

### R5 — batting reconciliation test is vacuous · agree · order 1

Proposed fix:
- Add `teamStats.batting` totals to the fixture allowlist in `scripts/make_fixtures.py`.
- The test compares against the **latest** raw snapshot per game, not every snapshot.
- Full outer join on `(game_pk, side)`. Missing sides and null required totals are
  failing rows, not skipped rows.
- Add a correction fixture: two snapshots of one game with different totals. It passes
  against the latest snapshot and would have failed under the old logic.
- Mutation demo, recorded in the PR: dropping a player, dropping a side, and nulling a
  total each make the test fail.
- Sweep the other singular tests for the same empty-input and null-comparison pattern.

### R6 — name variants multiply roster rows · agree · order 1

Proposed fix: the crosswalk grain is **one row per `espn_player_id`**. The canonical name
is the one from the latest roster snapshot. Name fallback runs on that canonical name
only. Add a uniqueness test on the crosswalk grain, exercised through
`int_fantasy__roster_days` since the crosswalk is ephemeral. Add unit tests for accent
variants, one ID with two names, ambiguous names, ID-over-name precedence, and
unresolved IDs.

### R7 — auth errors swallowed · agree · order 1

Proposed fix: `except AuthExpired: raise` ahead of the per-item catch. Test: expiry
after one successful period makes no further requests, and the CLI exits non-zero.
Transport retries (timeouts, connection errors) go into `HttpClient` separately, bounded,
with their own test.

## Intermediate tests (order 2)

These are small synthetic dbt unit tests, not bigger fixtures:
- A doubleheader summed into one player-day.
- A two-way player with batting and pitching on the same day.
- An off-day zero versus a missing-boxscore unknown. This needs the review's
  completeness/resolution flag, so milestone 9 can tell them apart.
- Every summed component, for the ratio categories.

## Comments on the documentation edits

- Accurate, and worth keeping. Being open about known gaps is a portfolio strength.
- **`README.md`:** reduce the two "the review found…" passages to one short "Known gaps"
  line that links the review, so the README leads with what the project does. Also fix
  the stray line break after "20,542 pitching lines," and rewrap the long line in the
  "Not planned" paragraph.
- **`02-intermediate-and-marts.md` amendments:** "milestone 9 marts read from the
  intermediate interfaces, and reconciliation may read staging" changes the design. The
  implementing side agrees with it, but it should be marked as a **decision taken
  2026-09-27** rather than as review guidance.
- **Status tracking:** the review's remediation table is the single place for remediation
  status. The design progress tables are not updated per fix, only per milestone.

## Questions for the reviewer

1. Accept the resequencing: milestone 9 before R1, R3 and R4, with the hard deadlines
   stated above?
2. Same-second collision policy for R3: fail loudly, or sub-second `fetched_at`?
3. R1 legacy captures: settled-by-`fetched_at` fallback, or a one-time refetch of all 180
   periods while ESPN still serves the 2026 league?
4. Anything in "Assumptions to challenge" that you consider a **blocker** for milestone 9,
   rather than a checklist item to handle within it?
