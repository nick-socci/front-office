# Code review — 2026-09-27

Reviewed commit `8484d06` (milestone 8 merged in PR #14). Scope: ingestion, staging,
intermediate models, fixture generation, automated tests, CI, and design/progress docs.
This review changes documentation only. Findings below remain open; passing existing
checks does not close them. Historical full-season claims were read, not independently
revalidated against the private warehouse or live APIs.

## Review progress and evidence

| Work | Status | Evidence |
|---|---|---|
| Read implementation and milestone plans | Complete | Findings and plan amendments below |
| Python test suite | Complete | 100 passed |
| Ruff lint and format | Complete | Passed; 34 files formatted |
| Strict mypy | Complete | Passed; 17 source files |
| Isolated fixture load/build | Complete | 10 raw responses; 158 PASS, 1 WARN, 0 ERROR; 159 executed nodes |
| Targeted failure probes | Complete | Request-key collision, rollover skip, sidecar interruption, and repeated auth rejection reproduced |
| Documentation reconciliation | Complete | Milestone 8 linked to actual merge PR; README scope/counts corrected |
| Remediation | Not started | Ordered work and acceptance criteria below |

The dbt build used the existing installed packages and the `dev` target with
`FO_DUCKDB_PATH` pointed at a temporary fixture database, `anonymize: true`, and temporary
artifact/log directories. It exercised the same models as CI without modifying the real
warehouse. Breakdown: 4 seeds, 21 materialized models, 131 data tests, 3 unit tests.
The warning was `stg_idmap__covers_started_players` (one result). No coverage percentage
was measured; test counts are not a coverage metric.

## Findings, ordered by priority

### R1 — P1: active roster snapshots can be frozen before their final state

Location: `ingestion/src/front_office/espn/rosters.py:50–63`.

Fetch period 100 while `latestScoringPeriod=100`, change a lineup later that day, then run
with `latestScoringPeriod=101`: `needs_fetch` returns false merely because a file exists.
It never checks whether that file was fetched after period 100 closed. Daily ingestion
can permanently miss the final lineup, corrupting all downstream attribution. The probe
confirmed the skip. `test_roster_is_skipped_once_its_period_is_over` encodes the unsafe
assumption instead of testing a transition.

Record the source status at capture and require a successful post-close snapshot before
marking a period settled. Test active → closed → repeated closed runs, plus a scheduler
outage spanning several periods. Preserve the historical-backfill fast path only when
its capture is known to be final.

### R2 — P1: ESPN identity is lost at both loading and staging

Locations: `landing.py:38–42`, `load.py` primary key/incoming deduplication,
`dbt/macros/espn_latest_response.sql:18–24`, and ESPN extractor metadata.

ESPN league and season are in URL paths and landing partitions, but `request_key` uses
only query parameters. The loader discards URL and partitions. Two leagues with the same
endpoint, parameters and second-resolution fetch timestamp collapse into one row: the
probe landed two settings responses and inserted only one. Even with distinct timestamps,
`fo_espn_latest` selects one response globally, or one per scoring period, not one per
league/season as its comment promises. Loading 2027 can replace the visible 2026 season.
Transactions additionally expose neither league nor season in staging.

Carry explicit league/season identity through raw storage and staging; migrate/rebuild
from existing metadata sidecars so old data is handled too. Partition latest-response
selection by that identity plus period. Audit uniqueness/relationship/count tests for
full compound keys. `stg_espn__scoring_periods` also generates every league to the global
maximum final period; generate each league's own range. Acceptance: two leagues and two
seasons, including identical timestamps and unequal season lengths, coexist without
loss, duplicates, or cross-attribution.

### R3 — P1: a sidecar failure creates an orphan that ingestion will never repair

Locations: `landing.py:97–98`; `_has_landed` in MLB boxscores and ESPN rosters;
`load.py` missing-metadata handling.

The payload and sidecar are individually atomic, not atomic as a pair. Failure on the
second rename leaves a payload that skip logic treats as landed, while the loader skips
it. The probe injected a sidecar failure: an old boxscore was neither refetched nor
loaded. The existing crash test fails the first rename and misses this boundary.

Define a committed-response protocol (for example, sidecar/manifest published last and
required by all readers). Incomplete pairs must be retried or quarantined, including
historical settled entities. Test failure at each write/rename boundary and recovery on
the next run. Also reject or uniquely identify same-second rewrites: filenames and raw
keys currently allow an allegedly append-only response to be overwritten/ignored.

### R4 — P1: the settle-window refresh can skip the corrections it is intended to capture

Location: `ingestion/src/front_office/mlb/boxscore.py:96–104`; design step 0.

Once any boxscore exists, only today's age relative to `official_date` controls refresh.
A boxscore fetched immediately after a game and revisited eight days later is skipped,
even if it was never fetched near the end of the correction window. Specifically, the
planned October 5 run skips an already-landed September 27 game (eight days old).
Suspended games resumed much later make `official_date` an especially weak proxy for
completion. This is established by the skip predicate, not a claim about observed source
corrections.

Track the last successful capture and a defensible completion/settlement boundary;
require a final capture after that boundary. Until fixed, the October 5 refresh needs
`--refresh` (currently refetches all settled games). Test a missed week of runs and a
resumed game with an old official date. Seven days is an operational policy, not proof
that no later corrections occur.

### R5 — P2: the strongest batting reconciliation test is ineffective in CI and stale across snapshots

Locations: `dbt/tests/stg_mlb__batting_totals_match_team_stats.sql`;
`scripts/make_fixtures.py:build_mlb_boxscores`.

The test compares deduplicated player totals with *every* raw team-total snapshot.
A legitimate correction therefore fails against an older snapshot. Conversely, both
committed boxscores omit `teamStats`; the review query found 2 boxscores and 0 populated
home team-hit totals. Comparisons with null produce no failing rows, so CI passes without
reconciling anything. An inner join also hides missing modeled team-sides.

Keep allowlisted team totals in fixtures; select the latest raw snapshot per game;
use a complete comparison that reports missing sides and required totals. Add a correction
fixture with different old/new totals. Demonstrate that removing a player, a whole side,
or a required total makes the test fail. Review other singular tests for empty-input and
null-comparison passes.

### R6 — P2: player-name variants can multiply roster rows

Locations: `dbt/models/intermediate/fantasy/int_fantasy__player_crosswalk.sql` (`entries`)
and `int_fantasy__roster_days.sql` (crosswalk join).

The helper selects distinct `(espn_player_id, player_name)` but its consumer joins only
on player ID. Two spellings for one ID create two matches for every roster entry. Current
uniqueness/count tests should detect the result, but the build then fails instead of
handling a normal name correction. This is a conditional bug established from join grain;
it was not observed in the fixture data.

Define the crosswalk grain explicitly and enforce it: either resolve each ID once using
a documented canonical-name rule, or retain name variants and join on that full key.
Test accent variants, renamed players, ambiguous names, ID precedence and unresolved IDs.
An ephemeral model can be tested through its consumers; materialization is not required
solely to make these behaviors testable.

### R7 — P2: roster backfill suppresses fail-fast authentication errors

Location: `ingestion/src/front_office/espn/rosters.py:89–101`.

`HttpClient` raises `AuthExpired`, but the outer catch-all logs it and tries every remaining
period. The probe returned 401 for three periods and observed three requests. The CLI
usually detects bad credentials in settings first, but expiry during roster collection
still hits this path. Re-raise authentication failures and separate recoverable per-item
errors from run-wide failures. Test expiry after a successful period and verify there are
no subsequent requests. Add bounded retries for transient transport errors separately;
the current retry loop only handles HTTP statuses, not timeouts/connection failures.

## Coverage assessment

Good coverage exists for status retries, request spacing, credential repr, loader
idempotency, privacy allowlists, innings units, zero-plate-appearance batting, staging
keys and row-count preservation. CI runs both Python and dbt, which is valuable.

The important missing coverage is behavioral:

| Area | Required cases |
|---|---|
| Ingestion lifecycle | Rollover/final capture, missed settle window, orphan recovery, auth expiry, transport timeout, CLI failure exit |
| Identity | Multiple leagues/seasons, same timestamp, request path identity, migration of old metadata |
| Intermediate arithmetic | Doubleheaders, batting plus pitching on one day, off-day zeroes, every relevant summed component |
| Player resolution | ID precedence, accent fallback, duplicate names, one ID with multiple names, unresolved starters |
| Snapshot semantics | Updated/deleted source entities, corrected totals, old vs new snapshots, nonempty comparisons |
| Transaction completeness | Pagination, page boundaries, nested-message truncation, duplicate events |
| Calendar | Historical fetch date, frozen postseason status, DST boundaries, different league lengths, suspended/resumed games |

The fixture warehouse contains **zero doubleheader player-days and zero two-way
player-days**. Of 429 started-player rows, only 18 join to an MLB appearance; most exercise
zero filling. There are three dbt unit tests, all in staging, and none in intermediate.
Add small synthetic expected-output dbt unit tests rather than expanding fixtures blindly.
Keep privacy checks, but do not interpret their parameterized count as analytics coverage.
No full-season ESPN score/winner reconciliation exists yet; it is milestone 9 work.

## Assumptions to challenge before implementing marts

- **One reconciled matchup does not establish general attribution.** Validate all teams,
  periods and categories, including suspended games and two-way players. Started-player
  days currently carry both batting and pitching production regardless of slot. Establish
  which production the platform counts for each role before summing it.
- **Zero production is not proof of an off day.** A missing boxscore or unresolved ID also
  becomes zero with `played=false`. Add source-completeness and resolution diagnostics so
  downstream marts can distinguish unknown production from verified zero.
- **Fetch date is not inherently a historical calendar anchor.** The scoring-date model
  assumes the reported latest period advances with the capture date. Persist/validate
  season anchors across snapshots; test a historical fetch where status has stopped moving.
  The opening-day check can detect a shift, but cannot establish the rule for every league.
- **One response is not proof of a complete transaction log.** The extractor fixes offset
  at zero, limit at 2,000 topics and 25 messages per set, without a completeness check.
  Add pagination or explicitly fail when completeness cannot be established. Latest-only
  staging can otherwise drop earlier events as a limited result window moves.
- **Contracts prove shape, not platform compatibility.** Scoring periods and category keys
  still encode platform conventions. The milestone 9 text also calls for direct staging
  references despite the neutral-interface rule. Use intermediate interfaces for production
  marts and keep source-specific reconciliation in a separate adapter/test boundary.
- **BigQuery migration is more than changing JSON macros.** Direct `from_json`, `unnest`,
  `json_keys`, `strip_accents`, `generate_series`, casts and date arithmetic remain in models.
  Treat portability as unverified until a representative adapter spike compiles and runs.
- **Incremental lookback needs an invalidation policy.** Roster, boxscore and ID-map
  corrections can change closed historical periods. Start with full rebuilds at this scale;
  adopt incremental models only after equivalence and late-correction tests exist.
- **Hindsight lineup value is not decision quality.** An assignment solver optimizes its
  scalar, not all category totals or matchup win probability. Ratios couple players through
  denominators; per-player z-scores are only a surrogate. Define “never worse” against the
  same scalar, handle zero variance/zero innings and feasible empty slots, and label the
  result hindsight opportunity rather than manager skill. Bench-median replacement value
  also needs a bias/availability sensitivity analysis.
- **Platform disagreement is not automatically a model bug.** Stat corrections, rounding,
  scoring eligibility and minimum-innings rules may differ. Record unexplained residuals
  and source capture times rather than widening tolerances or declaring universal proof.

## Recommended remediation sequence

Sequence revised after the [implementer's response](2026-09-27-review-response.md)
and [reviewer follow-up](2026-09-27-reviewer-follow-up.md).

**Status lives in GitHub issues, not here.** Each item below is an issue carrying its
agreed fix and acceptance criteria; ordering is encoded as issue dependencies and the
[milestones](https://github.com/nick-socci/front-office/milestones). An issue closes with
the PR that satisfies it, and operational evidence is recorded as issue comments. This
table maps the agreed order to those issues and is not updated per fix.

| Order | Work | Issues | Acceptance gate |
|---|---|---|---|
| 0 | Historical input audit; time-bound step 0 backfill/refresh and backup | [#8](https://github.com/nick-socci/front-office/issues/8), [#18](https://github.com/nick-socci/front-office/issues/18), [#19](https://github.com/nick-socci/front-office/issues/19), [#20](https://github.com/nick-socci/front-office/issues/20), [#21](https://github.com/nick-socci/front-office/issues/21); audit in [#17](https://github.com/nick-socci/front-office/pull/17) | Required roster captures proven final; played-game set covered by readable, loaded pairs; unknowns explicit; operational evidence recorded |
| 1 | R5, R6, R7 | [#22](https://github.com/nick-socci/front-office/issues/22), [#23](https://github.com/nick-socci/front-office/issues/23), [#24](https://github.com/nick-socci/front-office/issues/24) | Reconciliation mutations fail; name variants preserve grain deterministically; auth stops immediately |
| 2 | Intermediate unit tests and completeness diagnostics | [#25](https://github.com/nick-socci/front-office/issues/25) | Doubleheaders, two-way days, rates' components, off-day vs missing/unresolved inputs exercised |
| 3 | Milestone 9 reconciliation | [#10](https://github.com/nick-socci/front-office/issues/10) | Validated calendar; relevant sides/categories compared; attribution rules checked; residuals explained |
| 4 | R2: source identity and rebuild | [#28](https://github.com/nick-socci/front-office/issues/28) | Before any second league/season load; two leagues × two seasons survive raw load and full build |
| 5 | R1, R3, R4: general capture lifecycle fixes | [#27](https://github.com/nick-socci/front-office/issues/27), [#29](https://github.com/nick-socci/front-office/issues/29), [#30](https://github.com/nick-socci/front-office/issues/30), [#31](https://github.com/nick-socci/front-office/issues/31), [#32](https://github.com/nick-socci/front-office/issues/32) | Before scheduled daily ingestion or 2027 opening day, whichever comes first; transition/fault tests pass |
| 6 | Performance/portability work | — | Measured need, representative adapter proof, full/incremental equivalence |

Step 0 proceeds on its calendar schedule; milestone 9 development need not wait for the
October refresh, but completion must satisfy the existing step 0 requirement. Deferring
R3 requires auditing and repairing incomplete pairs after every intervening backfill.
Transaction completeness is required before milestone 10. Scope restrictions and remaining
fix-design conditions are detailed in the reviewer follow-up.

Useful refactors: centralize completed-snapshot discovery shared by MLB/ESPN; centralize
request identity construction; retain thin source-specific fetchers; use bounded batches
in `load_landing_zone` rather than materializing and reserializing all history each run.
Avoid a generic ingestion framework until these concrete invariants are settled.

For every completed item, append the implementing commit/PR, exact check and result,
remaining limitation, and validation date. Distinguish implemented, locally verified,
merged and operationally verified states. Do not mark milestone 9 or step 0 complete on
the strength of this fixture review.
