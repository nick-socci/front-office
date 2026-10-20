# Planted failures

A data test the CI fixtures cannot make fail (they hold no verified row, no playoff
matchup) is shown to fail here, on a copy of the CI warehouse with a row planted
(spec 0174, ADRs 0087 and 0088). `scripts/check_plants.py` runs every plant in the gates.

- `<test name>.yml`, one per test (this folder is outside every dbt path, so dbt never
  parses it). Only `.yml` files are read; the test name must exist in the manifest.
- The file holds `plants:`, a list. Each plant has `name` (unique in the file), `why` (the
  failure it stands for), `sql` (a string or a list; each entry exactly one INSERT, UPDATE
  or DELETE, which must change a row), `expect`, and optionally `materialize`.
- `expect` is `pass`, or `{status: fail|warn, failures: <int >= 1>}`: dbt's status and its
  exact failure count for that one test, run on the copy.
- `materialize: [schema.view]` turns a view into a table of the same name and rows first,
  in the copy only, so that a statement can change it.
- A plant that changes no row fails by name; an UPDATE that sets the values a row already
  has changes nothing.
- `_empty_in_ci.yml` lists relations with no row in CI: `relations:` of `relation`
  (`schema.name`), `reason`, and `link` (an issue or ADR the reason rests on).
- A generic test whose `where` admits no CI row needs a plant file; an empty relation needs
  an entry in `_empty_in_ci.yml`.
