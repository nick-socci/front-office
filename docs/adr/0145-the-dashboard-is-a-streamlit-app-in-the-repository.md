# 0145. The dashboard is a Streamlit app in the repository

- Status: proposed
- Date: 2026-11-21
- Spec: [0232-dashboard](../specs/0232-dashboard/design.md) · Issue: #232

## Context

The README's roadmap has named Streamlit since sub-project 2. The repo is Python with `uv`, the
owner is fluent in Python, and every other component is held by the gates. The pages are a handful of
filtered tables and charts over marts (spec R3).

## Decision drivers

- Pages are code in the repository, reviewed and tested by the gates.
- One language and toolchain.
- Small enough to run beside the daily run on `mothership`.

## Considered options

1. **Streamlit**: Python pages, `AppTest` under pytest, a `dashboard` dependency group.
2. **Evidence**: pages as SQL and markdown, built into a static site.
3. **Metabase**: a JVM service whose questions and dashboards are saved in its own database.

## Decision

Chosen by the owner on 2026-11-22, at the spec's walkthrough: **option 1**, as recommended. Its pages are Python the gates can lint, type and render headless.
Evidence suits SQL-only pages well, but it brings Node and npm into a Python repo for one
component, plus a build step in the run. Metabase's pages live outside the repository, so they
could not be reviewed or tested.

## Consequences

- Good: pages are tested in CI with the rest (`AppTest`, spec R7.2).
- Bad / accepted cost: Streamlit and its dependencies (pandas, pyarrow, altair) join the run's image,
  so one image still deploys and rolls back everything. A second image is the fallback if size or
  build time hurts (spec task 9).
- Follow-ups: none.
