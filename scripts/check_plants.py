"""Show that the data tests CI cannot exercise do fail, by planting a failing row.

Spec 0174, ADRs 0087 and 0088. The CI fixtures hold no verified row and no playoff matchup,
so a test restricted to those passes on zero rows and proves nothing. This does two things
on the warehouse the fixture build made (dbt/ci.duckdb, opened read-only) and its manifest:

- Detect (R3). For every generic test attached to a model or seed it counts the relation's
  rows and the rows the test's `where` admits. A `where` that admits none needs a plant
  file; a relation with no rows needs an exemption in dbt/plants/_empty_in_ci.yml.
- Plant (R2). For each plant in dbt/plants/<test>.yml it copies the warehouse into a scratch
  directory, turns the listed views into tables, runs the plant's statements (each must
  change a row, or the plant fails and its test is not run), then runs the real `dbt test`
  on that one test and compares dbt's status and failure count with the plant's `expect`.

The register's format is in dbt/plants/README.md. Every problem is printed, not just the
first. Exit 1 if there is any. The pure parts take dicts, strings and counts so that
ingestion/tests/test_check_plants.py reaches them without dbt.

Usage:  uv run python scripts/check_plants.py --db dbt/ci.duckdb
        [--manifest dbt/target/manifest.json] [--plants-dir dbt/plants] [--project-dir dbt]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

EMPTY_FILE = "_empty_in_ci.yml"
_FILE_KEYS = {"plants"}
_REQUIRED_PLANT_KEYS = {"name", "why", "sql", "expect"}
_PLANT_KEYS = _REQUIRED_PLANT_KEYS | {"materialize"}
_EXEMPTION_KEYS = {"relation", "reason", "link"}
_RELATION = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED = {
    duckdb.StatementType.INSERT: "INSERT",
    duckdb.StatementType.UPDATE: "UPDATE",
    duckdb.StatementType.DELETE: "DELETE",
}
# Comments are removed (string literals are kept) so that the UPDATE's target table is found
# even when the entry opens with a comment.
_COMMENT = re.compile(r"(/\*.*?\*/|--[^\n]*)|'(?:[^']|'')*'", re.DOTALL)
_TARGET = re.compile(
    r"^\s*(?:update\s+(?:only\s+)?|insert\s+(?:or\s+\w+\s+)?into\s+|delete\s+from\s+)"
    r"([A-Za-z0-9_.\"]+)",
    re.IGNORECASE,
)
_BEFORE_IMAGE = "__plant_before"


# --- the register (R1) -------------------------------------------------------------------


def _statements(entry: Any) -> list[str] | None:
    """The sql of a plant as a list of strings, or None if it is neither form."""
    if isinstance(entry, str):
        return [entry]
    if isinstance(entry, list) and entry and all(isinstance(s, str) for s in entry):
        return list(entry)
    return None


def statement_problem(sql: str) -> str | None:
    """Why this entry is not exactly one INSERT, UPDATE or DELETE as DuckDB parses it."""
    try:
        parsed = duckdb.extract_statements(sql)
    except duckdb.Error as exc:
        return f"does not parse ({exc})"
    if len(parsed) != 1:
        return f"must be exactly one statement, found {len(parsed)}"
    if parsed[0].type not in _ALLOWED:
        return f"must be an INSERT, UPDATE or DELETE, found {parsed[0].type.name}"
    return None


def _expect_problem(expect: Any) -> str | None:
    if expect == "pass":
        return None
    if isinstance(expect, dict):
        if set(expect) != {"status", "failures"}:
            return "expect must be `pass` or {status: fail|warn, failures: <int >= 1>}"
        if expect["status"] not in ("fail", "warn"):
            return f"expect status must be fail or warn, not {expect['status']!r}"
        failures = expect["failures"]
        if isinstance(failures, bool) or not isinstance(failures, int) or failures < 1:
            return f"expect failures must be an integer of at least 1, not {failures!r}"
        return None
    return "expect must be `pass` or {status: fail|warn, failures: <int >= 1>}"


def validate_plant_file(stem: str, content: Any) -> list[str]:
    """Every problem with one plant file, naming the file and the plant (R1.1, R1.4)."""
    if not isinstance(content, dict):
        return [f"{stem}: the file must be a mapping with a `plants` list"]
    problems = [f"{stem}: unknown key {k!r}" for k in sorted(set(content) - _FILE_KEYS)]
    plants = content.get("plants")
    if not isinstance(plants, list) or not plants:
        return [*problems, f"{stem}: `plants` must be a non-empty list"]
    seen: set[Any] = set()
    can_fail = False
    for index, plant in enumerate(plants, start=1):
        if not isinstance(plant, dict):
            problems.append(f"{stem}: plant {index} must be a mapping")
            continue
        label = f"{stem}: plant {plant.get('name', f'#{index}')!r}"
        problems += [
            f"{label}: missing key {k!r}" for k in sorted(_REQUIRED_PLANT_KEYS - set(plant))
        ]
        problems += [f"{label}: unknown key {k!r}" for k in sorted(set(plant) - _PLANT_KEYS)]
        for key in ("name", "why"):
            if key in plant and not (isinstance(plant[key], str) and plant[key].strip()):
                problems.append(f"{label}: {key!r} must be a non-empty string")
        if isinstance(plant.get("name"), str) and plant["name"].strip():
            if plant["name"] in seen:
                problems.append(f"{label}: duplicate plant name")
            seen.add(plant["name"])
        if "expect" in plant:
            if message := _expect_problem(plant["expect"]):
                problems.append(f"{label}: {message}")
            elif plant["expect"] != "pass":
                can_fail = True
        if "sql" in plant:
            statements = _statements(plant["sql"])
            if statements is None:
                problems.append(f"{label}: sql must be a string or a non-empty list of strings")
            else:
                for n, sql in enumerate(statements, start=1):
                    if message := statement_problem(sql):
                        problems.append(f"{label}: sql entry {n} {message}")
        if "materialize" in plant:
            views = plant["materialize"]
            if not isinstance(views, list) or not all(
                isinstance(v, str) and _RELATION.match(v) for v in views
            ):
                problems.append(f"{label}: materialize must be a list of schema.relation")
    if not can_fail:
        problems.append(f"{stem}: no plant expects the test to fail or warn")
    return problems


def validate_empty_file(content: Any) -> list[str]:
    """Every problem with _empty_in_ci.yml: each entry needs a relation, reason and link."""
    name = EMPTY_FILE
    if not isinstance(content, dict) or set(content) != {"relations"}:
        return [f"{name}: the file must be a mapping with only a `relations` list"]
    entries = content["relations"]
    if not isinstance(entries, list):
        return [f"{name}: `relations` must be a list"]
    problems: list[str] = []
    seen: set[Any] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            problems.append(f"{name}: entry {index} must be a mapping")
            continue
        label = f"{name}: {entry.get('relation', f'entry {index}')!r}"
        problems += [f"{label}: missing key {k!r}" for k in sorted(_EXEMPTION_KEYS - set(entry))]
        problems += [f"{label}: unknown key {k!r}" for k in sorted(set(entry) - _EXEMPTION_KEYS)]
        for key in sorted(_EXEMPTION_KEYS & set(entry)):
            if not isinstance(entry[key], str) or not entry[key].strip():
                problems.append(f"{label}: {key!r} must say something")
        relation = entry.get("relation")
        if isinstance(relation, str) and not _RELATION.match(relation):
            problems.append(f"{label}: relation must be schema.name")
        if relation in seen:
            problems.append(f"{label}: duplicate relation")
        seen.add(relation)
    return problems


def stale_problems(
    plant_stems: list[str],
    test_names: set[str],
    exempt_relations: list[str],
    relation_rows: dict[str, int],
) -> list[str]:
    """A plant file for no test, an exemption for a relation with rows or none tested (R1.3)."""
    problems = [
        f"{stem}.yml: plant file for a test the manifest does not have"
        for stem in plant_stems
        if stem not in test_names
    ]
    for relation in exempt_relations:
        if relation not in relation_rows:
            problems.append(f"{EMPTY_FILE}: {relation} is not the relation of any generic test")
        elif relation_rows[relation] > 0:
            problems.append(
                f"{EMPTY_FILE}: {relation} has {relation_rows[relation]} rows in CI; "
                "remove its exemption"
            )
    return problems


# --- detection (R3) ----------------------------------------------------------------------


def classify(relation_rows: int, admitted_rows: int) -> str:
    """What a generic test's two counts demand: `needs_exemption`, `needs_plant` or `ok`."""
    if relation_rows == 0:
        return "needs_exemption"
    if admitted_rows == 0:
        return "needs_plant"
    return "ok"


def generic_tests(manifest: dict[str, Any]) -> list[dict[str, str | None]]:
    """The generic tests attached to a model or seed: name, relation and where."""
    nodes = manifest["nodes"]
    found = []
    for node in nodes.values():
        if node["resource_type"] != "test" or not node.get("test_metadata"):
            continue
        target = nodes.get(node.get("attached_node") or "")
        if target is None or target["resource_type"] not in ("model", "seed"):
            continue
        found.append(
            {
                "name": node["name"],
                "relation": f"{target['schema']}.{target['alias']}",
                "where": node["config"].get("where"),
            }
        )
    return sorted(found, key=lambda t: str(t["name"]))


def test_names(manifest: dict[str, Any]) -> set[str]:
    """The name of every data test in the manifest, generic and singular: what a plant file
    may be named for."""
    return {
        str(node["name"]) for node in manifest["nodes"].values() if node["resource_type"] == "test"
    }


def count_rows(con: duckdb.DuckDBPyConnection, relation: str, where: str | None) -> int:
    sql = f"select count(*) from {relation}"
    if where:
        sql += f" where ({where})"
    row = con.execute(sql).fetchone()
    assert row is not None
    return int(row[0])


# --- planting (R2) -----------------------------------------------------------------------


def _short(sql: str) -> str:
    text = " ".join(sql.split())
    return text if len(text) <= 160 else text[:157] + "..."


def run_statement(con: duckdb.DuckDBPyConnection, sql: str) -> str | None:
    """Run one plant statement; return why it changed no row, or None if it changed one.

    Every kind is judged the same way, by the target table before and after:
    `count(after EXCEPT ALL before) + count(before EXCEPT ALL after)` must be at least one
    (R2.3). DuckDB counts a row an UPDATE matched even when it set the values the row
    already had, so its row count cannot show that. The statement's own result rows are
    never read: a RETURNING clause would turn them into something other than a count.
    """
    try:
        stripped = _COMMENT.sub(lambda m: " " if m.group(1) else m.group(0), sql)
        match = _TARGET.match(stripped)
        if match is None:
            return f"cannot find the table of: {_short(sql)}"
        table = match.group(1)
        con.execute(f"create temp table {_BEFORE_IMAGE} as select * from {table}")
        try:
            con.execute(sql)
            row = con.execute(
                f"select (select count(*) from (select * from {table} "
                f"except all select * from {_BEFORE_IMAGE})) "
                f"+ (select count(*) from (select * from {_BEFORE_IMAGE} "
                f"except all select * from {table}))"
            ).fetchone()
            changed = int(row[0]) if row else 0
        finally:
            con.execute(f"drop table if exists {_BEFORE_IMAGE}")
    except duckdb.Error as exc:
        return f"failed ({exc}): {_short(sql)}"
    if changed < 1:
        return f"changed no row: {_short(sql)}"
    return None


def materialize(con: duckdb.DuckDBPyConnection, relation: str) -> str | None:
    """Replace a view by a table of the same schema, name and rows; None if it worked."""
    schema, name = relation.split(".")
    try:
        is_view = con.execute(
            "select count(*) from duckdb_views() where not internal "
            "and schema_name = ? and view_name = ?",
            [schema, name],
        ).fetchone()
        if not is_view or is_view[0] != 1:
            return f"cannot materialize {relation}: it is not a view"
        con.execute(f"create table {schema}.{name}__plant as select * from {schema}.{name}")
        con.execute(f"drop view {schema}.{name}")
        con.execute(f"alter table {schema}.{name}__plant rename to {name}")
    except duckdb.Error as exc:
        return f"cannot materialize {relation} ({exc})"
    return None


def describe_expect(expect: Any) -> str:
    return "pass" if expect == "pass" else f"{expect['status']} {expect['failures']}"


def judge(expect: Any, results: list[tuple[str, int | None]]) -> tuple[bool, str]:
    """Whether dbt's one result meets `expect`, and what dbt gave (R2.4, R2.5)."""
    if len(results) != 1:
        return False, f"{len(results)} results"
    status, failures = results[0]
    got = status if status in ("pass", "error") else f"{status} {failures}"
    if status == "error":
        return False, got
    if expect == "pass":
        return status == "pass", got
    return status == expect["status"] and failures == expect["failures"], got


def run_dbt_test(
    test: str, copy: Path, target_path: Path, project_dir: Path
) -> list[tuple[str, int | None]] | str:
    """Run the real `dbt test` on the copy; the (status, failures) results, or why it broke.

    Each plant's copy has a path of its own. dbt-duckdb keeps its DuckDB connection open
    between in-process invocations and opens a new one only when the profile's credentials
    change. With one path for every plant, the next plant's dbt would read the previous
    copy's pages (spec 0174, design.md, Amendments).
    """
    from dbt.cli.main import dbtRunner

    saved_cwd = Path.cwd()
    saved_env = {k: os.environ.get(k) for k in ("DBT_PROFILES_DIR", "FO_CI_DUCKDB_PATH")}
    os.environ["DBT_PROFILES_DIR"] = str(project_dir)
    os.environ["FO_CI_DUCKDB_PATH"] = str(copy)
    os.chdir(project_dir)
    try:
        outcome = dbtRunner().invoke(
            [
                "test",
                "--select",
                test,
                "--target",
                "ci",
                "--vars",
                "{anonymize: true}",
                "--target-path",
                str(target_path),
                "--quiet",
            ]
        )
    finally:
        os.chdir(saved_cwd)
        for key, value in saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    if outcome.exception is not None:
        return f"dbt raised {outcome.exception}"
    results = getattr(outcome.result, "results", [])
    return [(str(r.status.value), r.failures) for r in results]


def run_plant(
    db: Path,
    plant_dir: Path,
    target_path: Path,
    test: str,
    plant: dict[str, Any],
    project_dir: Path,
) -> tuple[bool, str]:
    """Plant one case in a fresh copy and judge dbt's result; (ok, what happened).

    The copy is `<plant_dir>/ci.duckdb`: named as the original, because a view stores the
    catalog it was built in, and in a directory of its own (see run_dbt_test).
    """
    plant_dir.mkdir()
    copy = plant_dir / "ci.duckdb"
    shutil.copyfile(db, copy)
    con = duckdb.connect(str(copy))
    try:
        for relation in plant.get("materialize", []):
            if message := materialize(con, relation):
                return False, message
        for sql in _statements(plant["sql"]) or []:
            if message := run_statement(con, sql):
                return False, f"statement {message}"
    finally:
        con.close()
    results = run_dbt_test(test, copy, target_path, project_dir)
    if isinstance(results, str):
        return False, results
    return judge(plant["expect"], results)


# --- the run -----------------------------------------------------------------------------


def load_register(plants_dir: Path) -> tuple[dict[str, list[dict[str, Any]]], list[Any], list[str]]:
    """The plants by test, the exemption entries, and the validation problems (R1.4)."""
    plants: dict[str, list[dict[str, Any]]] = {}
    exemptions: list[Any] = []
    problems: list[str] = []
    for path in sorted(plants_dir.glob("*.yml")):
        try:
            content = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            problems.append(f"{path.name}: not valid YAML ({exc})")
            continue
        if path.name == EMPTY_FILE:
            found = validate_empty_file(content)
            problems += found
            if not found:
                exemptions = content["relations"]
            continue
        found = validate_plant_file(path.stem, content)
        problems += found
        if not found:
            plants[path.stem] = content["plants"]
    return plants, exemptions, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / "dbt/target/manifest.json")
    parser.add_argument("--plants-dir", type=Path, default=REPO_ROOT / "dbt/plants")
    parser.add_argument("--project-dir", type=Path, default=REPO_ROOT / "dbt")
    args = parser.parse_args(argv)
    db: Path = args.db.resolve()
    project_dir: Path = args.project_dir.resolve()

    manifest = json.loads(args.manifest.read_text())
    plants, exemptions, register_problems = load_register(args.plants_dir)
    problems = list(register_problems)
    tests = generic_tests(manifest)

    # Detect, on the warehouse opened read-only (R2.1).
    relation_rows: dict[str, int] = {}
    zero_tests: dict[str, list[str]] = defaultdict(list)  # needs_exemption, by relation
    vacuous: list[str] = []  # needs_plant
    con = duckdb.connect(str(db), read_only=True)
    try:
        for test in tests:
            relation = str(test["relation"])
            try:
                if relation not in relation_rows:
                    relation_rows[relation] = count_rows(con, relation, None)
                admitted = count_rows(con, relation, test["where"])
            except duckdb.Error as exc:
                problems.append(f"{test['name']}: cannot count the rows it reads ({exc})")
                continue
            verdict = classify(relation_rows[relation], admitted)
            if verdict == "needs_exemption":
                zero_tests[relation].append(str(test["name"]))
            elif verdict == "needs_plant":
                vacuous.append(str(test["name"]))
    finally:
        con.close()

    exempt = [e["relation"] for e in exemptions]
    stale = stale_problems(sorted(plants), test_names(manifest), exempt, relation_rows)
    problems += stale
    malformed = bool(register_problems or stale)
    accounted = 0
    for name in vacuous:
        if name in plants:
            accounted += 1
        else:
            problems.append(
                f"{name}: its `where` admits no CI row and it has no plant file "
                f"(dbt/plants/{name}.yml)"
            )
    for relation, names in sorted(zero_tests.items()):
        if relation in exempt:
            accounted += len(names)
        else:
            problems.append(
                f"{relation}: no rows in CI and no exemption in {EMPTY_FILE}; "
                f"read by {', '.join(names)}"
            )
    zero_total = len(vacuous) + sum(len(n) for n in zero_tests.values())
    print(
        f"generic tests counted: {len(tests)}; reading zero rows: {zero_total}; "
        f"accounted for by a plant or an exemption: {accounted}"
    )

    # Plant (R2). Nothing runs while the register is malformed (R1.4).
    ran = 0
    if malformed:
        print("the register is malformed; no plant was run")
    else:
        with tempfile.TemporaryDirectory(prefix="check_plants_") as tmp:
            scratch = Path(tmp)
            for test_name, test_plants in plants.items():
                for plant in test_plants:
                    plant_dir = scratch / f"plant_{ran:03d}"
                    ok, got = run_plant(
                        db, plant_dir, scratch / "target", test_name, plant, project_dir
                    )
                    ran += 1
                    print(
                        f"{'PASS' if ok else 'FAIL'} {test_name} {plant['name']}: "
                        f"expected {describe_expect(plant['expect'])}, got {got}"
                    )
                    if not ok:
                        problems.append(
                            f"{test_name} {plant['name']}: expected "
                            f"{describe_expect(plant['expect'])}, got {got}"
                        )
        print(f"plants run: {ran}")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for problem in problems:
            print(f"  {problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
