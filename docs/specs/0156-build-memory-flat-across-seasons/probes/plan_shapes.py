"""Spec 0156 probe: which nodes parse the heavy endpoints' files, and what their plans gather.

A node parses a heavy endpoint's files when it reaches its capture view
(`stg_raw__espn_roster`, `stg_raw__espn_matchup_days`, `stg_raw__mlb_boxscore`,
`stg_raw__mlb_schedule`) through views alone; a table in between was built earlier and is
read, not parsed. For each such node this prints the operators in its DuckDB plan that
gather their whole input before emitting a row, with the endpoints whose files that input
reads:

    DELIM_JOIN   (LEFT_DELIM_JOIN, …) a `cross join unnest(...)` DuckDB did not stream
    CTE          a CTE, or a repeated subplan, DuckDB materialized

An operator's endpoints are found from the plan: each capture view joins READ_JSON to a
scan of `raw.captures` filtered on `endpoint='…'`, and that filter names it.

    uv run python docs/specs/0156-build-memory-flat-across-seasons/probes/plan_shapes.py \
        <warehouse.duckdb> <target-dir>

<target-dir> is the dbt target directory of a build into <warehouse.duckdb> (its
manifest.json and compiled/). Run from the repository root.
"""

from __future__ import annotations

import functools
import json
import re
import sys
from pathlib import Path
from typing import Any

import duckdb

HEAVY_VIEWS = {
    f"model.front_office.stg_raw__{source}_{endpoint}": endpoint
    for source, endpoint in (
        ("espn", "roster"),
        ("espn", "matchup_days"),
        ("mlb", "boxscore"),
        ("mlb", "schedule"),
    )
}
HEAVY = set(HEAVY_VIEWS.values())
ENDPOINT = re.compile(r"endpoint='([a-z_]+)'")


def walk(node: dict[str, Any]) -> list[dict[str, Any]]:
    """The node and everything under it."""
    found, stack = [], [node]
    while stack:
        current = stack.pop()
        found.append(current)
        stack.extend(current.get("children", []))
    return found


def endpoints_read(operator: dict[str, Any]) -> set[str]:
    """The endpoints whose files are read (READ_JSON) somewhere under this operator."""
    below = walk(operator)
    if not any(op["name"].startswith("READ_JSON") for op in below):
        return set()
    names: set[str] = set()
    for op in below:
        info = op.get("extra_info", {})
        if op["name"] == "SEQ_SCAN" and "captures" in str(info.get("Table", "")):
            filters = info.get("Filters", [])
            for text in filters if isinstance(filters, list) else [filters]:
                names.update(ENDPOINT.findall(text))
    return names


def gathering(plan: list[dict[str, Any]]) -> list[tuple[str, list[str]]]:
    """Each gathering operator over a heavy endpoint's read, with those endpoints."""
    result = []
    for root in plan:
        for op in walk(root):
            if "DELIM_JOIN" in op["name"] or op["name"] == "CTE":
                heavy = sorted(endpoints_read(op) & HEAVY)
                if heavy:
                    result.append((op["name"], heavy))
    return result


def main() -> None:
    warehouse, target = Path(sys.argv[1]), Path(sys.argv[2])
    nodes = json.loads((target / "manifest.json").read_text())["nodes"]

    @functools.cache
    def parses(unique_id: str) -> frozenset[str]:
        found: set[str] = set()
        for parent in nodes[unique_id]["depends_on"]["nodes"]:
            if parent in HEAVY_VIEWS:
                found.add(HEAVY_VIEWS[parent])
            elif parent in nodes and nodes[parent]["config"].get("materialized") in (
                "view",
                "ephemeral",
            ):
                found |= parses(parent)
        return frozenset(found)

    con = duckdb.connect()
    con.execute(f"attach '{warehouse}' as {warehouse.stem} (read_only)")
    readers = 0
    for unique_id, node in sorted(nodes.items()):
        if node["resource_type"] not in ("model", "test") or unique_id in HEAVY_VIEWS:
            continue
        if not parses(unique_id):
            continue
        readers += 1
        # A generic test's file is named by its (possibly hashed) `path`, under its yml.
        compiled = target / "compiled" / "front_office" / node["original_file_path"]
        if node["original_file_path"].endswith(".yml"):
            compiled = compiled / node["path"]
        rows = con.execute("explain (format json) " + compiled.read_text()).fetchall()
        found = gathering(json.loads(rows[0][1]))
        if found:
            ops = ", ".join(f"{name} over {'+'.join(eps)}" for name, eps in found)
            print(f"{node['resource_type']:5} {node['name'][:60]:60} {ops}")
    print(f"{readers} nodes parse a heavy endpoint")


if __name__ == "__main__":
    main()
