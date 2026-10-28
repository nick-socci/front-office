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
- Cover every heavy endpoint. A heavy endpoint with no capture in the CI warehouse compiles
  to an empty query, with no file read for a gathering operator to sit over, so its readers
  could not be judged: that fails (spec 0156, pre-PR review F1).
- Keep the register honest (R4.3, R4.4). An entry whose node no longer has that operator
  over that endpoint, or whose node is not a reader, fails: an entry cannot outlive its reason.

Payload check (spec 0134, ADR 0106). The endpoints that are not parsed into a structure keep
a `payload` column: their capture views call `fo_captures` with two arguments, and every
model or test that reaches one through views and ephemerals alone is a payload reader. The
same explain of a reader's compiled SQL is searched for an operator that repeats its input
once per list element (an UNNEST, an INOUT_FUNCTION named unnest, or a join with an unnest
under one side) and is fed a column named `payload`: that carries the whole file once per
element (AGENTS.md rule 1). No register entry can exempt it. Three probe queries that do
carry a payload must be flagged on every run, so a change in DuckDB's plan format cannot
switch the check off. A payload view needs a capture in the CI warehouse, compared by
(source, endpoint), and a column named `payload`. Blind spot: a payload renamed (`payload as
body`) is not seen. The lineup solver is registered on the connection from
fo_duckdb_functions so that its node can be explained.

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
# A third argument of exactly `none` declares nothing (the view keeps its payload column), so
# the lookahead excludes it; a name such as `none_structure` still matches.
_STRUCTURED_CALL = re.compile(
    r"""fo_captures\(\s*(['"])[^'"]*\1\s*,\s*(['"])([^'"]+)\2\s*,(?!\s*none\s*\))""", re.DOTALL
)
# fo_captures('<source>', '<endpoint>') or with an explicit `none` third argument: no structure,
# so the view keeps its payload column.
_PLAIN_CALL = re.compile(
    r"""fo_captures\(\s*(['"])([^'"]*)\1\s*,\s*(['"])([^'"]+)\3\s*(?:,\s*none\s*)?\)""",
    re.DOTALL,
)
_PAYLOAD = re.compile(r"\bpayload\b")
_NON_MULTIPLYING = {"SEMI", "ANTI", "MARK", "RIGHT_SEMI", "RIGHT_ANTI"}


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


def payload_views(nodes: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """unique_id -> (source, endpoint), for each model that calls fo_captures with two arguments."""
    found: dict[str, tuple[str, str]] = {}
    for unique_id, node in nodes.items():
        if node.get("resource_type") != "model":
            continue
        match = _PLAIN_CALL.search(node.get("raw_code") or "")
        if match:
            found[unique_id] = (match.group(2), match.group(4))
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


# --- a payload carried into an unnest (spec 0134, ADR 0106) ------------------------------


def _projections(op: dict[str, Any]) -> list[str]:
    """The operator's Projections as a list: DuckDB gives one column as a bare string."""
    value = (op.get("extra_info") or {}).get("Projections")
    if value is None:
        return []
    return [value] if isinstance(value, str) else [str(item) for item in value]


def _is_unnest(op: dict[str, Any]) -> bool:
    """An UNNEST, or the INOUT_FUNCTION DuckDB plans an unnest of an expression as."""
    name = op.get("name")
    return name == "UNNEST" or (
        name == "INOUT_FUNCTION" and (op.get("extra_info") or {}).get("Name") == "unnest"
    )


def _join_type(op: dict[str, Any]) -> str:
    return str((op.get("extra_info") or {}).get("Join Type", "")).upper()


def _is_join(op: dict[str, Any]) -> bool:
    """A cross product or join, not a delim join."""
    name = str(op.get("name", ""))
    return name == "CROSS_PRODUCT" or (name.endswith("JOIN") and "DELIM" not in name)


def _emits(op: dict[str, Any]) -> list[str]:
    """What the operator outputs: its Projections, else what its children emit.

    A semi, anti or mark join emits its first child only.
    """
    if "Projections" in (op.get("extra_info") or {}):
        return _projections(op)
    children = op.get("children", [])
    if _join_type(op) in _NON_MULTIPLYING:
        children = children[:1]
    return [column for child in children for column in _emits(child)]


def _carries_payload(op: dict[str, Any]) -> bool:
    return any(_PAYLOAD.search(column) for column in _emits(op))


def payload_carries(plan: list[dict[str, Any]]) -> list[str]:
    """Sorted unique names of the operators fed a payload.

    An unnest is fed its children. A multiplying join with an unnest under at least one child
    is fed the children with none under them: the list does not depend on the row.
    """
    found: set[str] = set()
    for root in plan:
        for op in _walk(root):
            children = op.get("children", [])
            if _is_unnest(op):
                inputs = children
            elif _is_join(op) and _join_type(op) not in _NON_MULTIPLYING:
                has_unnest = [any(_is_unnest(o) for o in _walk(c)) for c in children]
                inputs = (
                    [c for c, below in zip(children, has_unnest, strict=True) if not below]
                    if any(has_unnest)
                    else []
                )
            else:
                continue
            if any(_carries_payload(child) for child in inputs):
                found.add(str(op.get("name", "")))
    return sorted(found)


def payload_problems(found: dict[str, list[str]], endpoints: dict[str, list[str]]) -> list[str]:
    """A problem for each (node, operator) fed a payload; `endpoints` names what the node reads."""
    return [
        f"{node}: {operator} is fed a payload ({', '.join(endpoints.get(node, []))}); "
        "compute what it needs in a CTE before the unnest (AGENTS.md rule 1)"
        for node in sorted(found)
        for operator in sorted(set(found[node]))
    ]


def uncovered_pairs(
    payload_pairs: set[tuple[str, str]], captured: set[tuple[str, str]]
) -> list[str]:
    """A problem for each payload (source, endpoint) the CI warehouse holds no capture of."""
    return [
        f"{source}/{endpoint}: a payload endpoint with no capture in the CI warehouse; its "
        "readers' plans read no file and cannot be checked. Add a fixture capture of it"
        for source, endpoint in sorted(payload_pairs - captured)
    ]


def missing_payload_column(columns: dict[str, list[str]]) -> list[str]:
    """A problem for each payload view (name -> its column names) with no `payload` column."""
    return [
        f"{view}: a payload capture view with no column named payload; the check keys on that name"
        for view, names in sorted(columns.items())
        if "payload" not in names
    ]


# Each carries a payload into an unnest and must be flagged: an UNNEST, a CROSS_PRODUCT, and a
# FILTER between a CROSS_PRODUCT and its unnest.
PROBES = [
    (
        "header list column",
        "with h as (select payload, [1] as l from {relation}) "
        "select h.payload, e from h cross join unnest(h.l) as _u(e)",
    ),
    (
        "constant list",
        "select payload, e from {relation} cross join unnest([1, 2]) as _u(e)",
    ),
    (
        "constant list with a filter",
        "select payload, e from {relation} cross join unnest([1, 2]) as _u(e) where e > 1",
    ),
]


def probe_relation(
    payload: dict[str, tuple[str, str]],
    nodes: dict[str, Any],
    columns: dict[str, list[str]],
) -> str | None:
    """The relation_name of the first payload view (by unique_id) that has a payload column."""
    for unique_id in sorted(payload):
        node = nodes[unique_id]
        if "payload" in columns.get(node.get("alias") or node["name"], []):
            return str(node["relation_name"])
    return None


def probe_problems(results: dict[str, list[str]]) -> list[str]:
    """A problem for each probe whose plan the detector found no carry in."""
    return [
        f"probe '{name}' carries a payload into an unnest and was not flagged; "
        "the plan format has changed, so the payload check can no longer be trusted"
        for name, _ in PROBES
        if not results.get(name)
    ]


def register_functions(con: duckdb.DuckDBPyConnection) -> None:
    """Register the lineup solver as dbt's plugin does, so its node can be explained."""
    for directory in ("dbt/python_modules", "dbt/functions"):
        path = str(REPO_ROOT / directory)
        if path not in sys.path:
            sys.path.append(path)
    import fo_duckdb_functions as plugin  # noqa: PLC0415

    con.create_function(
        plugin.NAME,
        plugin.solve_lineup_period,
        [t for _, t in plugin.ARGUMENTS],
        plugin.RETURNS,
        null_handling="special",
    )


def uncovered(heavy_endpoints: set[str], endpoints_with_captures: set[str]) -> list[str]:
    """A problem for each heavy endpoint the CI warehouse holds no capture of."""
    return [
        f"{endpoint}: a heavy endpoint with no capture in the CI warehouse; its readers' plans "
        "read no file and cannot be checked. Add a fixture capture of it"
        for endpoint in sorted(heavy_endpoints - endpoints_with_captures)
    ]


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
    payload = payload_views(nodes)
    payload_reading = readers(nodes, {uid: endpoint for uid, (_, endpoint) in payload.items()})

    # The catalog is the file's stem: compiled SQL names it (`ci.staging.x`).
    con = duckdb.connect()
    con.execute(f"attach '{db}' as {db.stem} (read_only)")
    register_functions(con)
    found: dict[str, list[tuple[str, str]]] = {}
    found_payload: dict[str, list[str]] = {}
    operators = 0
    unnests = 0
    try:
        captured_pairs = {
            (row[0], row[1])
            for row in con.execute(
                f"select distinct source, endpoint from {db.stem}.raw.captures"
            ).fetchall()
        }
        captured = {endpoint for _, endpoint in captured_pairs}
        found_problems += uncovered(heavy_endpoints, captured)
        found_problems += uncovered_pairs(set(payload.values()), captured_pairs)

        columns: dict[str, list[str]] = {}
        for unique_id in sorted(payload):
            node = nodes[unique_id]
            view = node.get("alias") or node["name"]
            columns[view] = [
                row[0]
                for row in con.execute(
                    "select column_name from duckdb_columns() "
                    f"where database_name = '{db.stem}' and schema_name = '{node['schema']}' "
                    f"and table_name = '{view}' order by column_index"
                ).fetchall()
            ]
        found_problems += missing_payload_column(columns)

        if payload:
            relation = probe_relation(payload, nodes, columns)
            if relation is None:
                found_problems.append(
                    "no payload capture view has a payload column to probe; "
                    "the payload check cannot be shown to work"
                )
            else:
                probed: dict[str, list[str]] = {}
                for name, template in PROBES:
                    try:
                        rows = con.execute(
                            "explain (format json) " + template.format(relation=relation)
                        ).fetchall()
                        probed[name] = payload_carries(json.loads(rows[0][1]))
                    except (duckdb.Error, ValueError, IndexError) as exc:
                        probed[name] = []
                        found_problems.append(f"probe '{name}' cannot be explained ({exc})")
                found_problems += probe_problems(probed)

        for unique_id in sorted(set(reading) | set(payload_reading)):
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
            if unique_id in reading:
                for kind, endpoints in gathering(plan, heavy_endpoints):
                    operators += len(endpoints)
                    found.setdefault(node["name"], []).extend((kind, e) for e in endpoints)
            if unique_id in payload_reading:
                unnests += sum(1 for root in plan for o in _walk(root) if _is_unnest(o))
                carried = payload_carries(plan)
                if carried:
                    found_payload[node["name"]] = carried
    finally:
        con.close()

    names = {nodes[unique_id]["name"] for unique_id in reading}
    found_problems += problems(found, entries, names)
    payload_endpoints = {
        nodes[unique_id]["name"]: sorted(endpoints)
        for unique_id, endpoints in payload_reading.items()
    }
    found_problems += payload_problems(found_payload, payload_endpoints)
    print(
        f"readers of a heavy endpoint checked: {len(reading)}; "
        f"gathering operators over one: {operators}; registered: {len(entries)}; "
        f"payload readers explained: {len(payload_reading)}; "
        f"unnest operators in them: {unnests}"
    )
    if found_problems:
        print(f"\n{len(found_problems)} problem(s):")
        for problem in found_problems:
            print(f"  {problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
