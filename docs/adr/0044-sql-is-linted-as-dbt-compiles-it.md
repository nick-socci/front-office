# 0044. SQL is linted as dbt compiles it

- Status: proposed
- Date: 2026-10-09
- Spec: [0013-docs-lint-exposures](../specs/0013-docs-lint-exposures/design.md) · Issue: #13

## Context

A dbt model is a Jinja template, not SQL: `{{ ref('x') }}`, `{{ var('y') }}` and the
project's `fo_json_*` macros must be rendered before a linter can parse the file.
sqlfluff calls the thing that renders a *templater* and offers two for dbt projects.

Both were run over the whole project on 2026-10-09 (sqlfluff 4.4.0):

| | `dbt` templater | `jinja` templater |
|---|---|---|
| How it renders | asks dbt to compile the model | its own Jinja, with stand-ins for dbt's functions |
| Violations found | 1,843 | 1,851 |
| Run time | 62 s (53 s with fewer rules) | 127 s |
| Macro files (17) | skipped | linted: 8 violations |
| `{{ var('fantasy_scale_prior_matchups') }}` | rendered as `100` | rendered as the word `item` |
| Needs | the dbt project to parse: a profile, `dbt deps` | the macro directory |
| Extra package | `sqlfluff-templater-dbt`, same version as sqlfluff | none |

## Decision drivers

- What is linted is what runs.
- All JSON access goes through macros that will gain BigQuery variants; the linter must
  not need its own imitation of them.
- Gate time.

## Considered options

1. **The `dbt` templater.**
2. **The `jinja` templater** with `apply_dbt_builtins` and the macro path.
3. **`jinja` for macros and `dbt` for the rest**, as two runs.

## Decision

Recommended, for the owner to decide: **option 1**. The lint step runs after `dbt deps`
and the fixture warehouse step, against the `ci` target, from the repository root.

Option 2 lints a guess: a stand-in value where dbt would put the real one, and its own
rendering of macros whose output depends on the adapter. It took twice as long here.
Option 3 buys 17 short files for a second configuration and a third minute.

## Consequences

- Good: the linter and the build read the same compiled SQL.
- Good: about one minute added to the gates.
- Bad / accepted cost: macro files are not linted. They are 17 files that reviewers
  read; a model that uses a macro is linted with the macro's output in it.
- Bad / accepted cost: two packages to keep at one version.
- Bad / accepted cost: lint needs a parseable project, so it cannot run before
  `dbt deps` on a fresh clone.
- Follow-ups: when macros gain BigQuery variants, lint runs once per target.
