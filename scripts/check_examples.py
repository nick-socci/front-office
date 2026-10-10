"""Check every example query against the exposure that declares it, and run it.

Spec 0013 R3.2-R3.6. An exposure (dbt's way of declaring something outside dbt that reads
its models) is only as true as whoever wrote it. So for each file in docs/examples this
reads the SQL, finds the models it reads, and compares them with the `depends_on` of the
`analysis` exposure of the same name, in both directions. It also checks that the dashboard
exposure names every mart, that no exposure carries an owner email (the repo is public),
and that each example actually runs against a built warehouse.

Every problem is printed, not just the first. Exit 1 if there is any.

Usage:  uv run python scripts/check_examples.py --db dbt/ci.duckdb
        [--examples-dir docs/examples] [--models-dir dbt/models]
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


def run_examples(db: Path, files: list[Path]) -> list[str]:
    """Execute each example read-only; a failing one is a problem."""
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
            try:
                rows = con.execute(sql).fetchall()
            except duckdb.Error as error:
                problems.append(f"{path.name}: {str(error).splitlines()[0]}")
            else:
                print(f"{path.name}: ok, {len(rows)} rows")
    finally:
        con.close()
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--examples-dir", type=Path, default=REPO_ROOT / "docs/examples")
    parser.add_argument("--models-dir", type=Path, default=REPO_ROOT / "dbt/models")
    args = parser.parse_args(argv)

    files = sorted(args.examples_dir.glob("*.sql"))
    exposures = load_exposures(args.models_dir)
    marts = {p.stem for p in (args.models_dir / "marts").iterdir() if p.suffix in {".sql", ".py"}}
    problems = [
        *check_example_exposures({p.stem: p.read_text() for p in files}, exposures),
        *check_dashboard(marts, exposures),
        *check_owners(exposures),
        *run_examples(args.db, files),
    ]
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
