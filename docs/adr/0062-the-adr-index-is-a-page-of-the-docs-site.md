# 0062. The ADR index is a page of the docs site, generated from the ADR files

- Status: accepted
- Date: 2026-10-12
- Spec: [0133-generated-adr-index](../specs/0133-generated-adr-index/design.md) · Issue: #133
- Amends: [0042](0042-the-docs-site-is-built-in-ci-from-the-fixtures.md), for how many files the site holds

## Context

`docs/adr/README.md` has been a table of every ADR, kept by hand. Every spec PR appends
rows and every build edits them, so it is the one file that two unrelated PRs both
change. On `main` at `f6d2270` (2026-10-12), 53 merged PRs had edited it and nine merges
in the history were of two commits that conflict in it, all within two days; the same day the branches
of #83 and #143 conflicted there again.

The table repeats what each file's heading and `Status`, `Date` and `Spec` lines say,
and the copy drifts: 6 of 60 titles and 9 of 60 statuses read differently in the table
than in the file. All 60 headers have one shape, so the table can be generated.

A generated file that is committed does not remove the conflict: two PRs that each add
an ADR both regenerate it.

## Decision drivers

- No PR edits a file that another ADR-adding PR also edits.
- One place says what a decision's title and status are.
- No new long-lived write permission on the repository (ADR 0042's driver).
- A reader can still see every decision with its status in one table.

## Considered options

1. **A page of the docs site** — the site assembler writes `decisions.html` from the ADR
   files; nothing committed lists them.
2. **Committed, written by CI on `main`** — a job regenerates and commits the table after
   each merge; PRs never touch it.
3. **Committed, regenerated in each PR** — a script writes the table and a gate fails
   when it is stale.

## Decision

Chosen: **a page of the docs site**, because it is the only option in which nothing
shared is written by a PR or by a bot, and it needs no permission CI does not have.
Option 2 keeps the table on GitHub but gives CI `contents: write` and puts a second
commit on `main` after every merge that adds an ADR. Option 3 leaves the conflict in
place and only makes it quicker to resolve.

The page's title and status cells are the file's heading and `Status` line, whole; the
status cell also shows the file's `Amends` and `Supersedes` lines (spec 0133, *Amendments*,
2026-10-15). The site assembler holds four files where ADR 0042 and spec 0013 R1.3 said
three; the fourth is generated from committed files and is checked for account GUIDs like
the others.

## Consequences

- Good: two specs written in parallel, each adding an ADR, have no line in common.
- Good: a malformed ADR header fails the tests, where before it was only a row that
  looked odd.
- Bad / accepted cost: on GitHub itself a reader sees the filenames, and opens the site
  for status, date and spec. The page is as current as the last deploy.
- Bad / accepted cost: two PRs that take the same number no longer conflict; the header
  check finds the duplicate, at the latest on `main`.
- Follow-ups: the `adr`, `build` and `sync` skills still speak of adding a row to the
  index (nick-socci/claude-setup#6).
