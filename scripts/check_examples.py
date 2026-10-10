"""Check every example query against the exposure that declares it, and run it.

Spec 0013 R3.2-R3.6. An exposure (dbt's way of declaring something outside dbt that reads
its models) is only as true as whoever wrote it. So for each file in docs/examples this
reads the SQL, finds the models it reads, and compares them with the `depends_on` of the
`analysis` exposure of the same name, in both directions. It also checks that the dashboard
exposure names every mart, that no exposure carries an owner email (the repo is public),
and that each example actually runs against a built warehouse.

Running is not enough: an example that returns no rows runs. So each example is also held
to the rows, and the counts of rows with a value in named columns, stated in
docs/examples/expected_on_fixtures.yml (spec 0117, ADRs 0048 and 0049), after setting the
DuckDB variables the entry states.

Every problem is printed, not just the first. Exit 1 if there is any.

Usage:  uv run python scripts/check_examples.py --db dbt/ci.duckdb
        [--examples-dir docs/examples] [--models-dir dbt/models]
        [--expectations docs/examples/expected_on_fixtures.yml]
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import duckdb
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

# One left-to-right scan, so that a `--` inside a string is not a comment and a `'` inside
# a comment does not open a string. A doubled '' inside a literal is an escaped quote.
_NOISE = re.compile(r"/\*.*?\*/|--[^\n]*|'(?:[^']|'')*'", re.DOTALL)
# The same scan keeping string literals: `getvariable('v')` names its variable in a literal,
# which _NOISE would remove, but a commented-out call must not count.
_COMMENT = re.compile(r"(/\*.*?\*/|--[^\n]*)|'(?:[^']|'')*'", re.DOTALL)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_EXPECTATION_KEYS = {"rows", "variables", "rows_with_a_value"}
_RELATION = re.compile(r"\b(?:staging|intermediate|marts|reconciliation)\.([a-z0-9_]+)\b")
_REF = re.compile(r"""^\s*ref\(\s*(['"])([^'"]+)\1\s*\)\s*$""")

DASHBOARD = "front_office_dashboard"


def relations_read(sql_text: str) -> set[str]:
    """The distinct model names the SQL reads, ignoring comments and string literals."""
    return set(_RELATION.findall(_NOISE.sub(" ", sql_text)))


def load_exposures(models_dir: Path) -> list[dict[str, Any]]:
    """Every exposure in every yml file under the models dir."""
    found: list[dict[str, Any]] = []
    for path in sorted(models_dir.rglob("*.yml")):
        content = yaml.safe_load(path.read_text())
        if isinstance(content, dict) and content.get("exposures"):
            found.extend(content["exposures"])
    return found


def exposure_refs(exposure: dict[str, Any]) -> set[str]:
    """The model names in the exposure's `ref('name')` depends_on entries."""
    refs: set[str] = set()
    for entry in exposure.get("depends_on") or []:
        match = _REF.match(str(entry))
        if match:
            refs.add(match.group(2))
    return refs


def _non_refs(exposure: dict[str, Any]) -> list[str]:
    return [str(e) for e in exposure.get("depends_on") or [] if not _REF.match(str(e))]


def check_example_exposures(
    example_files: dict[str, str], exposures: list[dict[str, Any]]
) -> list[str]:
    """Compare each example (file stem -> SQL) with the analysis exposure of that name."""
    problems: list[str] = []
    analyses = {e["name"]: e for e in exposures if e.get("type") == "analysis"}
    for stem in sorted(example_files):
        if stem not in analyses:
            problems.append(f"{stem}: example has no exposure of type analysis named {stem}")
    for name in sorted(set(analyses) - set(example_files)):
        problems.append(f"{name}: analysis exposure matches no example file")
    for stem, sql in sorted(example_files.items()):
        read = relations_read(sql)
        if not read:
            problems.append(f"{stem}: no relation found in the example")
        exposure = analyses.get(stem)
        if exposure is None:
            continue
        for entry in _non_refs(exposure):
            problems.append(f"{stem}: depends_on entry {entry} is not a ref(...)")
        declared = exposure_refs(exposure)
        for name in sorted(read - declared):
            problems.append(f"{stem}: reads {name}, which its exposure does not name")
        for name in sorted(declared - read):
            problems.append(f"{stem}: exposure names {name}, which the example does not read")
    return problems


def check_dashboard(mart_names: set[str], exposures: list[dict[str, Any]]) -> list[str]:
    """The dashboard exposure must name every mart and nothing else."""
    matching = [e for e in exposures if e.get("name") == DASHBOARD]
    if len(matching) != 1:
        return [f"{DASHBOARD}: expected exactly one exposure, found {len(matching)}"]
    exposure = matching[0]
    problems: list[str] = []
    if exposure.get("type") != "dashboard":
        problems.append(f"{DASHBOARD}: type is {exposure.get('type')!r}, expected 'dashboard'")
    refs = exposure_refs(exposure)
    for name in sorted(mart_names - refs):
        problems.append(f"{DASHBOARD}: mart {name} is not named")
    for name in sorted(refs - mart_names):
        problems.append(f"{DASHBOARD}: {name} is not a mart")
    return problems


def check_owners(exposures: list[dict[str, Any]]) -> list[str]:
    """Every exposure has an owner name and no owner email."""
    problems: list[str] = []
    for exposure in exposures:
        owner = exposure.get("owner")
        owner = owner if isinstance(owner, dict) else {}
        label = exposure.get("name", "?")
        if not owner.get("name"):
            problems.append(f"{label}: owner.name is missing or empty")
        if "email" in owner:
            problems.append(f"{label}: owner.email must not be set (public repo)")
    return problems


def _without_comments(sql_text: str) -> str:
    """The SQL with comments removed and string literals left as they are."""
    return _COMMENT.sub(lambda m: " " if m.group(1) else m.group(0), sql_text)


def _is_whole_number(value: object) -> bool:
    # bool is a subclass of int, and `rows: true` would hold an example to nothing.
    return isinstance(value, int) and not isinstance(value, bool)


def load_expectations(path: Path) -> dict[str, dict[str, Any]]:
    """The parsed expectations file: example file stem -> what it returns on the fixtures."""
    content = yaml.safe_load(path.read_text())
    return content if isinstance(content, dict) else {}


def check_expectations(
    example_files: dict[str, str], expectations: dict[str, dict[str, Any]]
) -> list[str]:
    """Compare the stated expectations with the examples, before anything is run."""
    problems: list[str] = []
    for stem in sorted(set(example_files) - set(expectations)):
        problems.append(f"{stem}: example has no entry in the expectations")
    for stem in sorted(set(expectations) - set(example_files)):
        problems.append(f"{stem}: expectation matches no example file")
    for stem, entry in sorted(expectations.items()):
        if not isinstance(entry, dict):
            problems.append(f"{stem}: expectation is not a mapping")
            continue
        rows = entry.get("rows")
        if not _is_whole_number(rows) or rows < 1:
            problems.append(f"{stem}: rows must be a whole number of at least 1, got {rows!r}")
        for key in sorted(set(entry) - _EXPECTATION_KEYS, key=str):
            problems.append(f"{stem}: unknown key {key!r}")
        if "rows_with_a_value" in entry:
            counts = entry["rows_with_a_value"]
            if not isinstance(counts, dict):
                problems.append(f"{stem}: rows_with_a_value must be a mapping of column to count")
            else:
                for column, expected in sorted(counts.items(), key=str):
                    if not _is_whole_number(expected) or expected < 0:
                        problems.append(
                            f"{stem}: rows_with_a_value for {column} must be a whole number "
                            f"of at least 0, got {expected!r}"
                        )
        variables = entry.get("variables") or {}
        if not isinstance(variables, dict):
            problems.append(f"{stem}: variables must be a mapping")
            continue
        text = _without_comments(example_files.get(stem, ""))
        for name in variables:
            if not re.search(rf"getvariable\(\s*'{re.escape(str(name))}'\s*\)", text):
                problems.append(f"{stem}: sets variable {name}, which the example does not read")
    return problems


def _run_stated(
    con: duckdb.DuckDBPyConnection, path: Path, sql: str, entry: dict[str, Any]
) -> list[str]:
    """Run one example with its entry's variables; compare what it returns with the entry."""
    variables = entry.get("variables")
    variables = variables if isinstance(variables, dict) else {}
    for name in variables:
        if not _IDENTIFIER.fullmatch(str(name)):
            return [f"{path.name}: variable name {name!r} is not a plain identifier"]
    set_names: list[str] = []
    try:
        # `set variable` takes a placeholder for the value but not the name, hence the check.
        for name, value in variables.items():
            con.execute(f"set variable {name} = ?", [value])
            set_names.append(str(name))
        cursor = con.execute(sql)
        rows = cursor.fetchall()
        columns = [column[0] for column in cursor.description or []]
    except duckdb.Error as error:
        return [f"{path.name}: {str(error).splitlines()[0]}"]
    finally:
        # A variable left set would change the next example's defaults.
        for name in set_names:
            con.execute(f"reset variable {name}")
    print(f"{path.name}: ok, {len(rows)} rows")
    problems: list[str] = []
    stated = entry.get("rows")
    if _is_whole_number(stated) and len(rows) != stated:
        problems.append(f"{path.name}: states {stated} rows, returned {len(rows)}")
    counts = entry.get("rows_with_a_value")
    for column, expected in sorted((counts if isinstance(counts, dict) else {}).items()):
        if column not in columns:
            problems.append(f"{path.name}: states a count for column {column}, which it lacks")
            continue
        if not _is_whole_number(expected):
            continue  # check_expectations reports it; `True` must not compare equal to 1
        found = sum(1 for row in rows if row[columns.index(column)] is not None)
        if found != expected:
            problems.append(
                f"{path.name}: states {expected} rows with a value in {column}, found {found}"
            )
    return problems


def run_examples(db: Path, files: list[Path], expectations: dict[str, dict[str, Any]]) -> list[str]:
    """Execute each example read-only; a failing one, or one off its expectation, is a problem."""
    if not db.exists():
        return [f"{db}: database does not exist"]
    problems: list[str] = []
    con = duckdb.connect(str(db), read_only=True)
    try:
        for path in files:
            # Lines starting with `.` are DuckDB command-line directives, not SQL.
            sql = "\n".join(
                line for line in path.read_text().splitlines() if not line.startswith(".")
            )
            entry = expectations.get(path.stem)
            problems.extend(_run_stated(con, path, sql, entry if isinstance(entry, dict) else {}))
    finally:
        con.close()
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--examples-dir", type=Path, default=REPO_ROOT / "docs/examples")
    parser.add_argument("--models-dir", type=Path, default=REPO_ROOT / "dbt/models")
    parser.add_argument("--expectations", type=Path, default=None)
    args = parser.parse_args(argv)
    # The default follows --examples-dir, so it can only be resolved after parsing.
    expectations_path = args.expectations or args.examples_dir / "expected_on_fixtures.yml"

    files = sorted(args.examples_dir.glob("*.sql"))
    example_files = {p.stem: p.read_text() for p in files}
    exposures = load_exposures(args.models_dir)
    marts = {p.stem for p in (args.models_dir / "marts").iterdir() if p.suffix in {".sql", ".py"}}
    problems: list[str] = []
    expectations: dict[str, dict[str, Any]] = {}
    if expectations_path.exists():
        expectations = load_expectations(expectations_path)
    else:
        problems.append(f"{expectations_path}: expectations file does not exist")
    problems += [
        *check_example_exposures(example_files, exposures),
        *check_expectations(example_files, expectations),
        *check_dashboard(marts, exposures),
        *check_owners(exposures),
        *run_examples(args.db, files, expectations),
    ]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
