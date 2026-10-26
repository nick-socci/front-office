"""Show that no model or test gathers a heavy endpoint's files before it emits a row.

Spec 0156, ADR 0102. A heavy endpoint is one whose capture view declares a structure
(`fo_captures('mlb', 'boxscore', structure)`): its files are megabytes each, parsed as they
are read. DuckDB streams that parse unless the plan gathers it first, and two operators do:

    DELIM_JOIN   (LEFT_DELIM_JOIN, ...) a `cross join unnest(...)` it did not stream
    CTE          a CTE, or a repeated subplan, it materialized

This runs on the warehouse the fixture build made (dbt/ci.duckdb, opened read-only) and its
manifest:

- Find (R4.1). Every model and test that reaches a heavy capture view through views and
  ephemerals alone (a table between them was parsed when it was built) is a reader. A view
  is heavy when its source, `raw_code`, calls `fo_captures` with a third argument. The
  compiled SQL is not used for this: an endpoint with no captures under the landing root
  compiles to an empty query with no file read, and would be missed.
- Explain (R4.2). `explain (format json)` of each reader's compiled SQL. A gathering
  operator whose subtree reads files names its endpoints by the `endpoint='...'` filters on
  its scans of `raw.captures`. One over a heavy endpoint needs an entry in
  dbt/plan_shapes.yml for its node, operator and endpoint.
- Keep the register honest (R4.3, R4.4). An entry whose node no longer has that operator
  over that endpoint, or whose node is not a reader, fails: an entry cannot outlive its reason.

Every problem is printed, not just the first (R4.6). Exit 1 if there is any. The pure parts
take dicts and strings so that ingestion/tests/test_check_plan_shapes.py reaches them
without dbt.

Usage:  uv run python scripts/check_plan_shapes.py [--db dbt/ci.duckdb]
        [--manifest dbt/target/manifest.json] [--register dbt/plan_shapes.yml]
        [--project-dir dbt]
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Any

import duckdb
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

OPERATORS = ("delim_join", "cte")
_ENTRY_KEYS = {"node", "operator", "endpoint", "reason", "link", "measured"}
_MEASURED_KEYS = {"threads", "gb_2026", "gb_all_seasons", "on"}
_LINK = re.compile(r"ADR \d{4}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_ENDPOINT = re.compile(r"endpoint='([a-z_]+)'")
# fo_captures('<source>', '<endpoint>', <structure>): the third argument is the declaration.
_STRUCTURED_CALL = re.compile(
    r"""fo_captures\(\s*(['"])[^'"]*\1\s*,\s*(['"])([^'"]+)\2\s*,""", re.DOTALL
)


# --- finding the readers (R4.1) ----------------------------------------------------------


def heavy_views(nodes: dict[str, Any]) -> dict[str, str]:
    """unique_id -> endpoint, for each model that calls fo_captures with a structure."""
    found: dict[str, str] = {}
    for unique_id, node in nodes.items():
        if node.get("resource_type") != "model":
            continue
        match = _STRUCTURED_CALL.search(node.get("raw_code") or "")
        if match:
            found[unique_id] = match.group(3)
    return found


def readers(nodes: dict[str, Any], heavy: dict[str, str]) -> dict[str, frozenset[str]]:
    """unique_id -> the heavy endpoints it reaches through views and ephemerals alone."""
    cache: dict[str, frozenset[str]] = {}

    def reaches(unique_id: str) -> frozenset[str]:
        if unique_id not in cache:
            found: set[str] = set()
            for parent in nodes[unique_id].get("depends_on", {}).get("nodes", []):
                if parent in heavy:
                    found.add(heavy[parent])
                elif parent in nodes and nodes[parent].get("config", {}).get("materialized") in (
                    "view",
                    "ephemeral",
                ):
                    found |= reaches(parent)
            cache[unique_id] = frozenset(found)
        return cache[unique_id]

    return {
        unique_id: endpoints
        for unique_id, node in sorted(nodes.items())
        if node.get("resource_type") in ("model", "test")
        and unique_id not in heavy
        and (endpoints := reaches(unique_id))
    }


# --- reading a plan (R4.2) ---------------------------------------------------------------


def _walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    """The plan node and everything under it."""
    found, stack = [], [node]
    while stack:
        current = stack.pop()
        found.append(current)
        stack.extend(current.get("children", []))
    return found


def _endpoints_read(operator: dict[str, Any]) -> set[str]:
    """The endpoints whose files are read (READ_JSON) somewhere under this operator."""
    below = _walk(operator)
    if not any(str(op.get("name", "")).startswith("READ_JSON") for op in below):
        return set()
    names: set[str] = set()
    for op in below:
        info = op.get("extra_info") or {}
        if op.get("name") == "SEQ_SCAN" and "captures" in str(info.get("Table", "")):
            filters = info.get("Filters", [])
            for text in filters if isinstance(filters, list) else [filters]:
                names.update(_ENDPOINT.findall(str(text)))
    return names


def gathering(plan: list[dict[str, Any]], heavy: set[str]) -> list[tuple[str, tuple[str, ...]]]:
    """Each gathering operator over a heavy endpoint's read: (kind, sorted endpoints)."""
    result = []
    for root in plan:
        for op in _walk(root):
            name = str(op.get("name", ""))
            if "DELIM_JOIN" in name:
                kind = "delim_join"
            elif name == "CTE":
                kind = "cte"
            else:
                continue
            # A CTE's first child is its definition, what it materializes; the second is
            # the rest of the query, which reads it. Only the first says what it holds: a
            # CTE of manifest rows is not a gathered parse because the query reads files.
            gathered = op["children"][0] if kind == "cte" and op.get("children") else op
            endpoints = tuple(sorted(_endpoints_read(gathered) & heavy))
            if endpoints:
                result.append((kind, endpoints))
    return result


# --- the register (R4.3) -----------------------------------------------------------------


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _date(value: Any) -> bool:
    if isinstance(value, datetime.date):  # YAML reads an unquoted 2026-10-25 as a date
        return True
    if isinstance(value, str) and _DATE.fullmatch(value):
        try:
            datetime.date.fromisoformat(value)
        except ValueError:
            return False
        return True
    return False


def _measured_problems(measured: Any) -> list[str]:
    if not isinstance(measured, dict):
        return ["'measured' must be a mapping of threads, gb_2026, gb_all_seasons, on"]
    problems = [f"measured is missing {k!r}" for k in sorted(_MEASURED_KEYS - set(measured))]
    problems += [f"measured has unknown key {k!r}" for k in sorted(set(measured) - _MEASURED_KEYS)]
    threads = measured.get("threads")
    if "threads" in measured and (
        isinstance(threads, bool) or not isinstance(threads, int) or threads < 1
    ):
        problems.append("measured 'threads' must be a positive integer")
    for key in ("gb_2026", "gb_all_seasons"):
        if key in measured and not (_number(measured[key]) and measured[key] > 0):
            problems.append(f"measured {key!r} must be a positive number")
    if "on" in measured and not _date(measured["on"]):
        problems.append("measured 'on' must be a date, YYYY-MM-DD")
    return problems


def validate_register(content: Any) -> list[str]:
    """Every problem with dbt/plan_shapes.yml, naming the entry."""
    name = "plan_shapes.yml"
    if not isinstance(content, dict) or set(content) != {"entries"}:
        return [f"{name}: the file must be a mapping with only an `entries` list"]
    entries = content["entries"]
    if not isinstance(entries, list):
        return [f"{name}: `entries` must be a list"]
    problems: list[str] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            problems.append(f"{name}: entry {index} must be a mapping")
            continue
        label = f"{name}: {entry.get('node', f'entry {index}')!r}"
        problems += [f"{label}: missing key {k!r}" for k in sorted(_ENTRY_KEYS - set(entry))]
        problems += [f"{label}: unknown key {k!r}" for k in sorted(set(entry) - _ENTRY_KEYS)]
        for key in ("node", "endpoint", "reason"):
            if key in entry and not (isinstance(entry[key], str) and entry[key].strip()):
                problems.append(f"{label}: {key!r} must be a non-empty string")
        if "operator" in entry and entry["operator"] not in OPERATORS:
            problems.append(f"{label}: 'operator' must be one of {', '.join(OPERATORS)}")
        link = entry.get("link")
        if "link" in entry and not (isinstance(link, str) and _LINK.fullmatch(link.strip())):
            problems.append(f"{label}: link must be an ADR (ADR 0102)")
        if "measured" in entry:
            problems += [f"{label}: {m}" for m in _measured_problems(entry["measured"])]
        key3 = (entry.get("node"), entry.get("operator"), entry.get("endpoint"))
        if all(isinstance(part, str) for part in key3):
            if key3 in seen:
                problems.append(f"{label}: duplicate node, operator and endpoint")
            seen.add(key3)
    return problems


# --- judging (R4.2, R4.4, R4.6) ----------------------------------------------------------


def problems(
    found: dict[str, list[tuple[str, str]]],
    register_entries: list[dict[str, Any]],
    reader_names: set[str],
) -> list[str]:
    """Every unregistered operator and every stale or unplaced entry.

    `found` maps a reader's name to the (operator, endpoint) pairs its plan gathers.
    """
    registered = {(e["node"], e["operator"], e["endpoint"]) for e in register_entries}
    result: list[str] = []
    for node in sorted(found):
        for operator, endpoint in sorted(set(found[node])):
            if (node, operator, endpoint) not in registered:
                result.append(
                    f"{node}: {operator} over {endpoint} is not in plan_shapes.yml; "
                    "rewrite the model so the parse streams, or register it with its reason"
                )
    for node, operator, endpoint in sorted(registered):
        if node not in reader_names:
            result.append(
                f"plan_shapes.yml: {node} ({operator} over {endpoint}) names no model or test "
                "that reads a heavy endpoint; remove the entry"
            )
        elif (operator, endpoint) not in set(found.get(node, [])):
            result.append(
                f"plan_shapes.yml: {node} no longer has a {operator} over {endpoint}; "
                "remove the entry"
            )
    return result


# --- the run -----------------------------------------------------------------------------


def compiled_file(node: dict[str, Any], project_dir: Path) -> Path | None:
    """Where dbt wrote the node's compiled SQL, or None if the manifest does not say."""
    path = node.get("compiled_path")
    if not path:
        return None
    resolved = Path(path)
    return resolved if resolved.is_absolute() else project_dir / resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--db", type=Path, default=REPO_ROOT / "dbt/ci.duckdb")
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / "dbt/target/manifest.json")
    parser.add_argument("--register", type=Path, default=REPO_ROOT / "dbt/plan_shapes.yml")
    parser.add_argument("--project-dir", type=Path, default=REPO_ROOT / "dbt")
    args = parser.parse_args(argv)
    db: Path = args.db.resolve()
    project_dir: Path = args.project_dir.resolve()

    nodes = json.loads(args.manifest.read_text())["nodes"]
    found_problems: list[str] = []

    try:
        content = yaml.safe_load(args.register.read_text())
    except yaml.YAMLError as exc:
        content = None
        found_problems.append(f"plan_shapes.yml: not valid YAML ({exc})")
    else:
        found_problems += validate_register(content)
    entries: list[dict[str, Any]] = (
        content["entries"] if not found_problems and content is not None else []
    )

    heavy = heavy_views(nodes)
    heavy_endpoints = set(heavy.values())
    reading = readers(nodes, heavy)

    # The catalog is the file's stem: compiled SQL names it (`ci.staging.x`).
    con = duckdb.connect()
    con.execute(f"attach '{db}' as {db.stem} (read_only)")
    found: dict[str, list[tuple[str, str]]] = {}
    operators = 0
    try:
        for unique_id in reading:
            node = nodes[unique_id]
            path = compiled_file(node, project_dir)
            if path is None or not path.is_file():
                found_problems.append(
                    f"{node['name']}: compiled SQL not found ({path}); run dbt build first"
                )
                continue
            try:
                rows = con.execute("explain (format json) " + path.read_text()).fetchall()
                plan = json.loads(rows[0][1])
            except (duckdb.Error, ValueError, IndexError) as exc:
                found_problems.append(f"{node['name']}: cannot explain its compiled SQL ({exc})")
                continue
            for kind, endpoints in gathering(plan, heavy_endpoints):
                operators += len(endpoints)
                found.setdefault(node["name"], []).extend((kind, e) for e in endpoints)
    finally:
        con.close()

    names = {nodes[unique_id]["name"] for unique_id in reading}
    found_problems += problems(found, entries, names)
    print(
        f"readers of a heavy endpoint checked: {len(reading)}; "
        f"gathering operators over one: {operators}; registered: {len(entries)}"
    )
    if found_problems:
        print(f"\n{len(found_problems)} problem(s):")
        for problem in found_problems:
            print(f"  {problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
