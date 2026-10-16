# The ADR index is generated onto the docs site — requirements

Issue: #133 · Tier: M · Status: draft

## Problem

`docs/adr/README.md` is a table with one row per ADR, kept by hand. Every spec PR appends
rows to it and every build's first commit edits them, so two open PRs touch adjacent
lines of one file and the one that merges second conflicts. Counted on `main` on
2026-10-12 (design.md, *Claims ledger*): 53 merged PRs have edited the file, and nine
merges in the history are of two commits that conflict in it, all within two days. The conflict was
predicted and left for the owner to find twice (#124 with #125, #131 with #132), and on
2026-10-12 the branches of #83 and #143 conflicted there again.

The table also repeats what each ADR file already says in its heading and its `Status`,
`Date` and `Spec` lines, and the copy has drifted: 6 of 60 titles and 9 of 60 statuses
read differently in the table than in the file.

The owner chose on 2026-10-12 that the table is built onto the docs site and is no
longer committed.

## Goals

- No PR edits a file that another PR adding an ADR also edits.
- One place says what an ADR's title and status are: the ADR file.
- A reader can still see every decision with its status, date and spec in one table.
- A malformed ADR header fails the gates, naming the file.

## No-gos

Explicitly out of scope. Work that drifts here is escalated, not done.

- No ADR's decision text changes. No ADR header is rewritten to suit the generator: the
  60 that exist parse as they are.
- ADR bodies are not rendered on the site. The table links to each file on GitHub.
- No new CI permission, job or step, and no bot that commits to `main`.
- The workflow skills (`adr`, `build`, `sync`) live in another repository. What they say
  about "the index" is changed there, under nick-socci/claude-setup#6, not here.
- ADR numbers are not changed, and how the next number is chosen is not this spec's.

## Rabbit holes

Places this could sink time, and the decision already taken to avoid them.

- A markdown renderer for the status cell → the generator renders two things only,
  `[text](target)` links and `` `code` `` spans, and escapes everything else. No
  dependency is added.
- Making the page look like dbt's → it is one plain HTML table with a few lines of
  inline CSS. It is not part of dbt's viewer and does not try to be.
- Two PRs that take the same ADR number no longer conflict in git, because nothing is
  shared → the header check fails on duplicate numbers (R2.3), and numbering is the
  `adr` skill's job. See design.md, *Risks*.

## Requirements

### R1. The index is a page of the docs site

A reader of the published site sees every decision in one table.

- R1.1 WHEN the docs site is assembled, THE SYSTEM SHALL write `decisions.html` into it,
  generated from the files `docs/adr/NNNN-*.md` and from nothing else.
- R1.2 THE SYSTEM SHALL give the page one row per ADR file, in number order, with: the
  number, linked to the file on GitHub; the title, which is the text of the file's
  heading after `# NNNN. `; the file's `Status` line; its `Date`; and the spec its `Spec`
  line links, linked to that file on GitHub.
- R1.3 THE SYSTEM SHALL show the `Status` line whole, as the file has it, with its
  markdown links rendered as links to the files on GitHub and its code spans as code.
- R1.4 THE SYSTEM SHALL escape every piece of ADR text it writes into the page.
- R1.5 THE SYSTEM SHALL state on the page how many decisions it lists and how many have
  each status word (R2.2 says what the word is).
- R1.10 IF the ADR directory is missing or holds no ADR file, THEN THE SYSTEM SHALL fail
  the assembly, naming the directory: an empty table is never published.
- R1.6 IF an ADR file's heading or its `Status`, `Date` or `Spec` line cannot be read,
  THEN THE SYSTEM SHALL fail the assembly, naming the file, and leave nothing uploadable.
- R1.7 IF the assembled site holds a file other than `index.html`, `manifest.json`,
  `catalog.json` and `decisions.html`, or lacks one of them, or `decisions.html` holds a
  match of `privacy.GUID`, THEN THE SYSTEM SHALL fail before anything is uploaded,
  naming what it found. This amends spec 0013 R1.3; its other conditions stand.
- R1.8 THE SYSTEM SHALL copy dbt's three files by name as before (spec 0013 R1.4) and
  SHALL NOT copy `decisions.html` from anywhere: it is written by the assembler.
- R1.9 THE SYSTEM SHALL link the page from the site's overview, from `README.md` and
  from `docs/README.md`.

### R2. ADR headers are checked

The generator depends on the headers, so the gates hold them.

- R2.1 THE SYSTEM SHALL fail the tests, naming the file and the reason, IF an ADR file:
  does not open with `# NNNN. <title>`; has a heading number other than its filename's;
  has in its header no `Status`, `Date` or `Spec` line, or more than one of any of them;
  has a `Date` that is not `YYYY-MM-DD`; or has a `Spec` line without exactly one link.
- R2.2 The status word of an ADR is the run of lowercase letters that opens its `Status`
  line, which must be followed by a space, a comma, a semicolon or the end of the line:
  `accepted`, `accepted; …` and `accepted, …` all have the word `accepted`. THE SYSTEM
  SHALL fail the tests IF the word is not one of `proposed`, `accepted`, `superseded`.
- R2.3 THE SYSTEM SHALL fail the tests IF two ADR files have the same number.
- R2.4 THE SYSTEM SHALL fail the tests IF a relative link in an ADR's header (`Status`,
  `Spec`, `Amends`, `Supersedes`) names a file that does not exist.

### R3. No index is kept by hand

- R3.1 `docs/adr/README.md` SHALL say what an ADR is, what the three status words mean,
  that the directory listing is in number order, and where the table is, and SHALL hold
  no table of ADRs.
- R3.2 THE SYSTEM SHALL fail the tests IF `docs/adr/README.md` links any `NNNN-*.md`
  file: a link is the start of an index.
- R3.3 `AGENTS.md` SHALL say that the index is generated and that no file lists the ADRs.

## Expected values

How correctness is checked against real data, not just fixtures. The ADR files are the
real data here. Counts are as of `main` at `f6d2270` (2026-10-12) and are recounted at
build time, since #83 will have moved three ADRs from `proposed` to `accepted`.

| Check | Expected | How to verify |
|---|---|---|
| Rows on the generated page | one per ADR file: 60 | count of `docs/adr/[0-9]*.md` equals rows |
| Status words | 56 accepted, 3 proposed, 1 superseded, and no fourth word: six `Status` lines open `accepted;` or `accepted,` and count as accepted | the page's own counts (R1.5) |
| Header check on the files as they are | passes, with no ADR file edited | the R2 tests on `main` |
| Generated rows against the last hand-kept table (`git show f6d2270:docs/adr/README.md`) | number, file, date and spec target equal in all 60 | a comparison in the build's run evidence |
| The same comparison, titles | 6 differ: 0023, 0031, 0033, 0034, 0035, 0038, each because the table's title was longer than the heading | the same |
| The same comparison, statuses | 9 differ, each because the file says more; the first word agrees in all 60 | the same |
| Files in the assembled site | exactly 4 | the assembler's own check, and its test |
| Site check, negative | fails on each of: a fifth file, a missing `decisions.html`, a GUID in it, an ADR with no `Status` line, an ADR directory with no ADR in it | pytest cases (R1.6, R1.7, R1.10) |
| Header check, negative | fails on each condition of R2.1 to R2.4 and on R3.2, and each test is seen to fail | pytest cases |
