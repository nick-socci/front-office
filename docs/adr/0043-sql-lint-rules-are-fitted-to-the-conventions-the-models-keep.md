# 0043. SQL lint rules are fitted to the conventions the models already keep, and no rule may change a relation

- Status: proposed
- Date: 2026-10-09
- Spec: [0013-docs-lint-exposures](../specs/0013-docs-lint-exposures/design.md) · Issue: #13

## Context

sqlfluff is a SQL linter: rules with codes (`LT02` indentation, `ST06` column order…),
most of which it can also fix. Its defaults describe one house style; this project has
117 model and test files written to another, consistently.

Measured with sqlfluff 4.4.0, DuckDB dialect, line length 100, on 2026-10-09:

| Configuration | Violations | Files |
|---|---|---|
| Default rules | 1,843 | 105 of 117 |
| Join conditions "later table first", `and` aligned under `on`, `ST06`/`RF04`/`RF01` off | 774 | 94 of 117 |

In the default run: 1,355 are indentation (`LT02`), of which 827 are the `on … and …`
alignment the models use everywhere. All 169 `ST09` hits are one convention: the joined
table is written first (`on prior.x = categories.x`). `ST06` (22) wants plain columns
before calculated ones, and its fix reorders a model's output columns. `RF04` (44)
objects to column names that are keywords; satisfying it means renaming columns.
`RF01` (9) is all in `stg_espn__roster_entries`, where it reads DuckDB struct access
(`entry.playerId`) as a missing table. Two parse errors come from a CTE named `prior`,
a keyword in sqlfluff's grammar and valid in DuckDB.

## Decision drivers

- No relation changes: not a row, a column name, a column order or a type.
- The reformatting diff is as small as an honest lint allows, so it can be read.
- A rule that stays on must be one the project will actually obey.
- Every exception is visible in one file, with its reason.

## Considered options

1. **Rules fitted to the existing conventions**: configure the two conventions,
   turn off the rules that would change a relation or that misread DuckDB, fix the
   rest.
2. **Default rules, and let `sqlfluff fix` rewrite everything.**
3. **Layout and capitalisation rules only** (`LT*`, `CP*`).
4. **A formatter with no configuration** (`sqlfmt`) in place of a linter.

## Decision

Recommended, for the owner to decide: **option 1**, starting from:

- `preferred_first_table_in_join_clause = later` and `indented_on_contents = False`,
  because the code already does both everywhere.
- `ST06` and `RF04` off, because obeying them changes a relation.
- `RF01` off, because it cannot read struct access.
- `max_line_length = 100`, as ruff has.

For each rule still reporting after `sqlfluff fix`, the build either fixes it by hand
(a handful of places) or turns it off with a written reason, and lists both on the
issue for the owner. `prior` is renamed inside its model; nothing outside reads a CTE.

Option 2 reorders 22 models' columns and rewrites 169 join conditions against the
project's own convention, for a diff more than twice the size. Option 3 gives up the
rules that find real things (ambiguous references, unaliased expressions, unused
CTEs). Option 4 is not what the issue asks for, reformats every file to a style nobody
chose, and checks nothing but layout.

## Consequences

- Good: the reformatting is mostly indentation, and is proved to change nothing by
  comparing the real warehouse before and after (spec R2.4).
- Good: new SQL is held to the style the old SQL already has.
- Bad / accepted cost: about 774 changes across 94 files in one commit; `git blame`
  on those lines points at it. The commit is listed in `.git-blame-ignore-revs`.
- Bad / accepted cost: three rules are off project-wide, one of them (`RF01`) for the
  sake of a single model.
- Bad / accepted cost: the final rule list is settled during the build, within this
  decision's rule: fix, or turn off with a reason; never change a relation.
- Follow-ups: revisit `RF01` and the excluded rules at the BigQuery migration, where
  the dialect changes.
