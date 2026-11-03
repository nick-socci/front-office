"""Spec 0140, C1, C3, C5 and C9: what a full build billed, by the raw endpoint each node reads.

Kept with the spec so that its claims can be rerun. It is evidence, not part of the build.
Reads a populated build's run_results.json and a BigQuery target's manifest.json.

    uv run python <this> data/139/run_results_build1.json data/139/target_bq/manifest.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

RAW = "source.front_office.raw.api_responses"
HEAVY = {
    "stg_raw__mlb_boxscore",
    "stg_raw__espn_roster",
    "stg_raw__espn_matchup_days",
    "stg_raw__mlb_schedule",
}
# What each model billed on the probes' tables (C6).
MEASURED = {
    "model.front_office.stg_mlb__pitching_game_logs": 0.287e9,
    "model.front_office.stg_mlb__batting_game_logs": 0.439e9,
    "model.front_office.stg_espn__roster_entries": 0.042e9,
    "model.front_office.stg_espn__roster_entry_slots": 0.345e9,
    "model.front_office.stg_espn__player_game_stats": 1.369e9,
    "model.front_office.stg_espn__matchup_days": 0.021e9,
    "model.front_office.stg_espn__matchup_player_lines": 0.178e9,
}
BLOCK_FLOOR = 0.32e9  # C5: what a node reading a small endpoint is billed of its neighbours.
QUERY_MINIMUM = 10.5e6  # BigQuery bills at least 10 MiB a query, rounded up.
TYPED_BOXSCORE = 0.634e9  # C6: the whole table, for the one test that reads its team totals.


def raw_reads(node: str, nodes: dict[str, Any], seen: set[str]) -> set[str]:
    """The capture views, and `keys` for the table itself, that running `node` scans, following
    views and ephemeral models. A table stops the walk: it is billed for its own bytes."""
    found: set[str] = set()
    for parent in nodes.get(node, {}).get("depends_on", {}).get("nodes", []):
        if parent in seen:
            continue
        seen.add(parent)
        materialized = nodes.get(parent, {}).get("config", {}).get("materialized")
        if parent == RAW:
            found.add("keys")
        elif ".stg_raw__" in parent and materialized == "view":
            found.add(parent.rsplit(".", 1)[-1])
        elif materialized in ("view", "ephemeral"):
            found |= raw_reads(parent, nodes, seen)
    return found


def main(run_results: Path, manifest_path: Path) -> None:
    results = json.loads(run_results.read_text())["results"]
    manifest = json.loads(manifest_path.read_text())
    nodes = {**manifest["nodes"], **manifest["sources"]}
    billed: Counter[str] = Counter()
    counted: Counter[str] = Counter()
    estimate = 0.0
    for result in results:
        node = result["unique_id"]
        cost = (result.get("adapter_response") or {}).get("bytes_billed") or 0
        reads = raw_reads(node, nodes, set())
        heavy = reads & HEAVY
        if not reads:
            group = "no raw"
        elif heavy:
            group = "heavy: " + ", ".join(sorted(heavy))
        else:
            group = "small endpoints or keys only"
        billed[group] += cost
        counted[group] += 1
        if node in MEASURED:
            estimate += MEASURED[node]
        elif "batting_totals_match" in node:
            estimate += TYPED_BOXSCORE
        elif reads and cost:
            estimate += max(cost - BLOCK_FLOOR, QUERY_MINIMUM)
        else:
            estimate += cost
    print(f"total {sum(billed.values()) / 1e9:.2f} GB over {len(results)} nodes")
    for group, cost in billed.most_common():
        print(f"{cost / 1e9:7.2f} GB {counted[group]:4d} nodes  {group}")
    print(f"estimate on the chosen shape: {estimate / 1e9:.2f} GB")
    print(f"at one build a day: {30 * estimate / 2**40:.3f} TiB a month")
    print(f"builds in the free terabyte: {2**40 / estimate:.1f}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
