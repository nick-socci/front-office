# 0042. The docs site is built in CI from the fixtures, and deployed by the Pages actions

- Status: proposed
- Date: 2026-10-09
- Spec: [0013-docs-lint-exposures](../specs/0013-docs-lint-exposures/design.md) · Issue: #13

## Context

`dbt docs generate` writes a static site: `index.html` (the viewer), `manifest.json`
(every model's SQL, description, tests and dependencies) and `catalog.json` (column
names and types read from the warehouse). Something has to build those files and
something has to host them. The repository is public and the league is private.

Measured on the fixture warehouse, 2026-10-09: the three files are 1.8, 4.1 and 0.1 MB.
They hold no data rows: DuckDB reports no table statistics to the catalog, and the
manifest's only row-like content is the unit tests' inline rows, which are already
committed. The manifest does record the absolute path of the machine that built it
(`root_path`, 7 occurrences), and two UUIDs of dbt's own that match the project's
account-GUID pattern.

The warehouse must exist and be built before the catalog can be read, so the site
needs the same steps CI already runs: load the fixtures, `dbt deps`, `dbt build`.

## Decision drivers

- Nothing from the real season, and nothing from a person's machine, reaches the site.
- The site never shows a state of `main` that failed its gates.
- No new long-lived write permission on the repository.
- A broken docs build is found on the pull request, not after the merge.

## Considered options

1. **Generate in CI's existing job from the fixture warehouse; a second job deploys the
   artifact with GitHub's Pages actions, on pushes to `main` only.**
2. **A separate `docs.yml` workflow** that repeats the load and build, as
   `docs/design/02` sketched.
3. **Push the files to a `gh-pages` branch** from CI.
4. **Build from the real warehouse on the owner's machine** and publish by hand.
5. **No site: a lineage image committed to the README.**

## Decision

Recommended, for the owner to decide: **option 1**.

The `quality` job gains two steps after `dbt build`: `dbt docs generate`, then a script
that copies the three files into `site/` by name and checks them (spec R1.3). On a push
to `main` it uploads `site/` as a Pages artifact, and a `deploy-docs` job that `needs:
quality` deploys it. Only that job holds `pages: write` and `id-token: write`.

Option 2 builds the warehouse twice per push and can deploy a commit whose gates
failed, unless it is chained to CI, which is option 1 with more YAML. Option 3 needs
`contents: write` and grows the repository by about 6 MB a deploy. Option 4 gains
nothing (the catalog has no statistics to show on either warehouse), publishes a home
directory path, and puts the real warehouse one mistake from a public page. Option 5 is
stale the day after it is drawn and shows no model's SQL or tests.

## Consequences

- Good: the site is rebuilt from the same warehouse the tests just passed on.
- Good: published files are chosen by name, as fixtures are (AGENTS.md rule 2).
- Good: no token outside the deploy job can write anything.
- Bad / accepted cost: the site shows the fixtures' column types, not the season's.
  They are the same models; nothing a reader looks for differs.
- Bad / accepted cost: Pages must be enabled, with "GitHub Actions" as its source,
  before the first merge, or the deploy job fails on `main`. That is a repository
  setting and the owner's action.
- Bad / accepted cost: CI is one job longer on `main`, and a few seconds longer on
  pull requests.
- Follow-ups: when a real warehouse exists in the cloud (sub-project 3), whether the
  site should be built from it is a new decision.
