# 0127. An asset is one CLI command or one dbt model

- Status: proposed
- Date: 2026-11-15
- Spec: [0217-dagster-daily-pipeline](../specs/0217-dagster-daily-pipeline/design.md) · Issue: #217

## Context

Dagster is the description of the daily pipeline (ADR 0122). Its unit is the asset. The `front-office`
CLI is the boundary: `cli.py` says orchestration calls the commands rather than importing the
package. `backfill espn` bundles endpoints: its `--only` values are `pro-schedule`, `matchups`
(pro schedule, settings, matchups), `rosters` (settings, teams, rosters) and `matchup-days`, and the
full run adds transactions (spec C6). `backfill mlb --only` does split schedule, players and
boxscore.

## Decision drivers

- No change to what a CLI command fetches (spec no-go).
- No repeated ESPN call whose capture another step also makes.
- A UI that shows per-step status and lineage into dbt.

## Considered options

1. **One asset per CLI command**, plus one per dbt model.
2. **One asset per landed endpoint**, about eleven, mapped to the capture views.
3. **One asset for the whole CLI run**, then the dbt models.

## Decision

Chosen by the owner on 2026-11-15: **option 1**, as recommended.

It needs no CLI change, and each of MLB, ESPN, upload and build can be read and retried apart.
Option 2 would fetch ESPN settings two or three times a day or add `--only` modes first. Option 3
drops the per-step status that ADR 0122 chose Dagster for.

## Consequences

- Good: six hand-written assets and the dbt ones; the definitions stay close to the CLI.
- Bad / accepted cost: lineage between endpoints inside a command is not drawn.
- Follow-ups: split an ESPN command's endpoints into assets once a morning shows which one fails.
