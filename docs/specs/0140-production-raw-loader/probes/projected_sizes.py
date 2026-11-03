"""Spec 0140, C11: how large each heavy endpoint is once reduced to its declared structure.

Kept with the spec so that its claims can be rerun. It is evidence, not part of the build.
Reads 400 sampled payload files per endpoint directly, for sizes only, and prints no values.

    uv run python <this>
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

ENDPOINTS = (("espn", "roster"), ("espn", "matchup_days"), ("mlb", "boxscore"), ("mlb", "schedule"))
SAMPLE = 400


def project(value: Any, part: Any) -> Any:
    """`value` holding only what `part` of a structure declares."""
    if isinstance(part, str):
        return value
    if value is None:
        return None
    if isinstance(part, list):
        return [project(item, part[0]) for item in value] if isinstance(value, list) else None
    if "__map__" in part:
        if not isinstance(value, dict):
            return None
        return {key: project(item, part["__map__"]) for key, item in value.items()}
    if not isinstance(value, dict):
        return None
    return {key: project(value[key], inner) for key, inner in part.items() if key in value}


def size(document: Any) -> int:
    return len(json.dumps(document, separators=(",", ":")))


def main() -> None:
    text = Path("dbt/macros/capture_structures.sql").read_text()
    blocks = re.findall(r"{% set structure %}(.*?){% endset %}", text, re.S)
    random.seed(0)
    for (source, endpoint), block in zip(ENDPOINTS, blocks, strict=True):
        structure = json.loads(block)
        files = sorted(Path(f"data/raw/{source}/{endpoint}").rglob("payload.json"))
        sample = random.sample(files, min(SAMPLE, len(files)))
        whole = kept = 0
        for path in sample:
            document = json.loads(path.read_text())
            whole += size(document)
            kept += size(project(document, structure))
        print(
            f"{source}/{endpoint}: {len(files)} files, {len(sample)} sampled, "
            f"{whole / 1e6:.1f} MB whole, {kept / 1e6:.1f} MB kept, {kept / whole:.3f}"
        )


if __name__ == "__main__":
    main()
