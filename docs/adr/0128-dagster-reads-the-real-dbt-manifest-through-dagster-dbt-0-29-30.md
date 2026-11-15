# 0128. Dagster reads the real dbt manifest through dagster-dbt 0.29.30

- Status: proposed
- Date: 2026-11-15
- Spec: [0217-dagster-daily-pipeline](../specs/0217-dagster-daily-pipeline/design.md) · Issue: #217

## Context

Spec 0216 (C8) found dagster-dbt 0.29.28 raising `KeyError` on this project's manifest, first on a
unit test and then on a dbt function, and handed the choice to #217: a newer version, a manifest
filtered before Dagster reads it, or dbt as one asset. On 2026-11-15, dagster 1.13.30 and
dagster-dbt 0.29.30 read the real manifest (574 nodes, 231 unit tests, 1 function, dbt 1.12.5,
DuckDB parse) unfiltered and gave 80 assets, which are the 73 non-ephemeral models and 7 seeds
(spec C1, C2). Not yet tried: a BigQuery-target manifest and a real materialization.

## Decision drivers

- Per-model lineage and status in the UI.
- No step that can drift from dbt's own view of the project.
- Memory: the manifest is read by the daemon's code server and the UI.

## Considered options

1. **dagster-dbt at 0.29.30 or newer, the real manifest, one asset per model.**
2. **A manifest filtered before Dagster reads it**, as 0216's spike did.
3. **dbt as one asset** that shells out `dbt build`.

## Decision

Chosen by the owner on 2026-11-15: **option 1**, as recommended. Spec task 3 repeats the load on a
BigQuery-target manifest and runs a real materialization first; if either fails, option 2 is the
fallback and this ADR is amended.

Option 2 adds a step that can differ from dbt's own and hides nodes the selector builds. Option 3
leaves one box in the UI and no per-model retry.

## Consequences

- Good: 80 assets with lineage, tests attached to them as checks.
- Bad / accepted cost: a hard pin on a dagster-dbt that is 0.x and moves with dbt; an upgrade is a
  change that task 3's test (the loaded count equals the manifest's) catches.
- Follow-ups: the manifest is produced by `dbt parse` for the chosen target when the code location
  loads; #218 does that at the container's start.
