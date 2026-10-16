# Architecture decisions

One decision per record. `proposed` until the spec that carries it is approved.
Decisions made before 2026-10 are in [docs/design/](../design/).

**The table of every decision, with its status, date and spec, is a page of the docs
site: [decisions](https://nick-socci.github.io/front-office/decisions.html).** It is
generated from these files each time the site is built (ADR 0062), so no file here lists
them, and nothing is edited to add one.

Each record's header says, in this order:

- `Status`: one of three words, sometimes followed by what changed it.
  - `proposed`: written with a spec that is not yet approved.
  - `accepted`: the spec was approved, and the decision holds. A record partly changed by
    a later one stays `accepted` and says `amended by` that record.
  - `superseded`: a later record replaced it, and its `Status` says which.
- `Date`: the day it was written.
- `Spec`: the spec that carried it.
- `Amends` or `Supersedes`, when it changes an earlier record.

Files are numbered in the order the decisions were made, so the directory listing is in
that order, and the filename is the title.
