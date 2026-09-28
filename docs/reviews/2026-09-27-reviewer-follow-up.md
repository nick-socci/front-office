# Reviewer follow-up — 2026-09-27

Response to the [implementer's comments](2026-09-27-review-response.md).
No implementation changes or new full-season validation are implied by this response.
The [original review](2026-09-27-code-review.md#recommended-remediation-sequence)
remains the remediation status record.

## Answers to the four questions

1. **Accept resequencing, with an input-validation gate.** My original sequence was too
   broad as a prerequisite for developing milestone 9 against a fixed historical dataset.
   Fix R5/R6/R7, add the intermediate tests, and verify the historical inputs before
   treating reconciliation results as evidence. R1/R4 general automation can follow.
   R3 can follow only if the current landing zone and each intervening backfill are
   checked for incomplete pairs and those are repaired. It is not a daily-only defect.
   R2 must precede loading *any* second league or season, including an older season—not
   merely 2027. Keep these as explicit scope restrictions until fixed.
2. **Fail loudly on collisions; retain the existing timestamp format for now.** Sub-second
   timestamps reduce collisions but do not prevent overwrites. They also require changing
   `fo_parse_fetched_at` and testing compatibility/order across timestamp formats. Publish
   fully written temporary files without replacement; do not write directly into a final
   payload using `O_EXCL` and call that atomic. Test that a collision leaves the existing
   payload and metadata unchanged. If concurrency becomes a requirement, design a unique
   capture ID separately from the capture timestamp.
3. **Audit legacy captures first; refetch only those whose finality is unproven.** A capture
   timestamp after a *validated* league/period end boundary is acceptable historical
   evidence. Do not derive that boundary solely from the same unverified latest-status /
   fetch-date anchor under review. Do not assume all 180 captures qualify. Preserve the
   existing files, record the evidence, and refetch uncertain periods while the source
   still serves them. A blanket refetch is a fallback if the audit cannot establish
   finality, not a prerequisite for every historical capture.
4. **The blockers are missing inputs masquerading as zero, unvalidated calendar mapping,
   and ineffective reconciliation checks.** These block declaring milestone 9 correct;
   they need not block writing its models. Two-way slot attribution, suspended-game
   attribution, minimum-innings rules, rounding and corrections must be investigated
   within milestone 9 and any residuals resolved or explicitly scoped before completion.
   Transaction pagination blocks transaction-impact completeness in milestone 10, not
   matchup-score development. BigQuery portability and lineup/replacement-value choices
   remain later work. Full rebuilds avoid needing an incremental invalidation policy now.

## Corrections to the proposed rationale and operational gate

“The 2026 data has landed” is a hypothesis to check, not evidence that every required
capture is present and final. R3 affects manual backfills too; R4 already affects step 0.
R1 can affect a historical dataset if any of its snapshots were captured while active.
The implementer correctly proposes inspecting sidecars; that inspection must precede
relying on the claim that offseason captures are safe.

Use this gate for historical reconciliation:

- Inventory required roster periods and expected played MLB games through the fantasy
  dates; verify readable payload/sidecar pairs and that they actually loaded.
- Report missing, unresolved and incomplete inputs separately from verified zero
  production. A passing total comparison alone can hide offsetting omissions.
- Validate the scoring-date anchor and record evidence that the selected roster snapshots
  were captured after their periods closed.
- After each outstanding MLB backfill/refresh, compare the latest schedule's played-game
  set with committed boxscores and record failures, capture dates and backup verification.

Do not require exactly 2,430 boxscores as the completeness definition. That number is
currently the scheduled-game count; canceled or unplayed games need explicit dispositions.
Use expected played game IDs, with no unexplained missing games. Record unmatched schedule
entries separately. October 5 is a planned refresh date, not proof that a game completed
seven days earlier; late completions require a later refresh. The claim that “waiting
loses data” needs a demonstrated source-retention deadline; prompt backup is sensible
without asserting one.

## Fix-design feedback

**R1:** Captured source status is a good basis. Capture it close enough to the roster
request that a batch crossing a period boundary does not misrepresent finality. A stale
status that classifies a final capture as active is conservative; test that recovery.
“After the final period ended” needs the validated boundary described above, not merely
`latest == final` or today's date. Legacy unknowns must remain visible.

**R2:** Keeping URL and partitions is useful. Use normalized endpoint/path identity plus
canonical request parameters, not the raw full URL including query-string ordering. The
existing extractors store `str(response.request.url)`, which includes the query string.
Otherwise equivalent reordered requests acquire different identities. Include identity
for every source, preserve transactions' league/season, and test old-sidecar rebuilding.
Build into a separate warehouse and validate counts/keys before replacing the derived
store; retain the old warehouse until the replacement is verified.

**R3:** The sidecar-as-commit-marker design is reasonable if every reader uses it and
both files are readable and consistent. `_quarantine/` beneath the landing root is still
visited by today's recursive `rglob('*.json')`; explicitly exclude it or put it outside
that tree. An interrupted concurrent writer can temporarily look like an orphan, so
quarantine under a single-writer lock or otherwise distinguish active writes from
abandoned captures. Check orphan sidecars as well as orphan payloads. Test collisions
at both publication steps, not just the happy path of two fresh filenames.

**R4:** `fetched_at >= official_date + settle_window` fixes skipped runs for ordinary
games but does not establish seven days after completion. Specify timezone and date versus
instant boundaries. A resumption timestamp can represent a restart rather than final
completion; verify its meaning against the actual landed fields before using it. Use a
validated completion boundary or a conservative first-observed-Final boundary, document
its limitations, and test late finishes and resumed games. Do not mark this finding fixed
solely by adding a comparison to the original official date.

**R5:** Accept. Allowlist only the required batting-total fields, not the entire nested
object. The player-removal mutation must remove a player with nonzero checked production;
removing a zero-stat player cannot be detected by a sum invariant alone. Keep grain and
completeness checks alongside total comparisons. Also test empty expected/actual sides.

**R6:** Accept one row per ESPN ID. Define a deterministic tie-break for “latest”: all
periods in a backfill share a fetch stamp, so order by scoring period (and season) where
appropriate, with an explicit final tie-break. Retain each roster entry's original display
name. Add a tied-timestamp/name-variant test; the resolution must not depend on input order.

**R7 and intermediate tests:** Accept. Keep transport retry changes separately reviewable.
The missing-boxscore case needs an independently known expected game; absence of a player
stat row alone cannot distinguish an off day from a missing response. Include unresolved
IDs in the unknown-input cases and assert all components used by the scored categories.

## Documentation decisions

Accept a shorter README with a single known-gaps pointer, provided it does not restore
unqualified reliability or portability claims. Keep the dated validation results.
The intermediate-interface rule for production marts, with source-specific staging reads
allowed in reconciliation tests, is recorded as a **design decision taken 2026-09-27**.
The original design already stated the neutral-interface intent but contradicted it in
milestone 9; this decision resolves that contradiction.

The revised sequence in the original review supersedes its initial order. All remediation
items remain **not started**; this is agreement on an approach, not acceptance of fixes.
