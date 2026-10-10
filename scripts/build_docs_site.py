"""Assemble the public dbt docs site from exactly three files, or refuse to.

Spec 0013 R1.3, R1.4. The dbt docs site is public and the ESPN league is private, so the
site is built by copying `index.html`, `manifest.json` and `catalog.json` out of dbt's
target directory by name (never a directory copy: target/ also holds run results and
compiled SQL), then checking the copies:

- the output holds exactly those three files;
- every catalog node and source says it came from the `ci` database (fixtures), not the
  real-season warehouse;
- no JSON key in the manifest or catalog is one of privacy.FORBIDDEN_KEYS;
- privacy.GUID matches nothing in the text of any of the three, once dbt's own ids
  (`invocation_id`, `user_id`) are removed. A match is printed truncated, never whole.

On any problem all of them are printed, the copies are deleted and the output directory is
removed if this run created it, so a failed run leaves nothing uploadable. Exit 1.

Usage:  uv run python scripts/build_docs_site.py --target-dir dbt/target --out site
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from front_office.privacy import FORBIDDEN_KEYS, GUID, walk

FILES = ("index.html", "manifest.json", "catalog.json")


def _dbt_ids(documents: list[Any]) -> set[str]:
    ids: set[str] = set()
    for document in documents:
        metadata = document.get("metadata") if isinstance(document, dict) else None
        if isinstance(metadata, dict):
            for key in ("invocation_id", "user_id"):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    ids.add(value)
    return ids


def check_site(out_dir: Path) -> list[str]:
    """Every reason the assembled site must not be published."""
    problems: list[str] = []
    listing = {p.name for p in out_dir.iterdir()}
    for extra in sorted(listing - set(FILES)):
        problems.append(f"{extra}: not one of the three files the site may hold")
    for missing in sorted(set(FILES) - listing):
        problems.append(f"{missing}: missing from the site")
    if problems:
        return problems

    texts = {name: (out_dir / name).read_text() for name in FILES}
    parsed = {name: json.loads(texts[name]) for name in ("manifest.json", "catalog.json")}

    catalog = parsed["catalog.json"]
    for section in ("nodes", "sources"):
        for key, entry in (catalog.get(section) or {}).items():
            database = (entry.get("metadata") or {}).get("database")
            if database != "ci":
                problems.append(f"catalog.json {section} {key}: database is {database!r}, not 'ci'")

    for name, document in parsed.items():
        for path, key, _ in walk(document):
            if key in FORBIDDEN_KEYS:
                problems.append(f"{name}: forbidden key {key} at {path}")

    ids = _dbt_ids(list(parsed.values()))
    for name, text in texts.items():
        for dbt_id in ids:
            text = text.replace(dbt_id, "")
        for match in sorted({m.group(0) for m in GUID.finditer(text)}):
            problems.append(f"{name}: GUID-shaped value {match.strip('{}')[:8]}…")
    return problems


def _counts(manifest: dict[str, Any]) -> str:
    nodes = (manifest.get("nodes") or {}).values()

    def of(kind: str) -> int:
        return sum(1 for n in nodes if n.get("resource_type") == kind)

    return (
        f"{of('model')} models, {of('seed')} seeds, {len(manifest.get('sources') or {})} sources, "
        f"{of('test')} data tests, {len(manifest.get('unit_tests') or {})} unit tests, "
        f"{len(manifest.get('exposures') or {})} exposures"
    )


def assemble(target_dir: Path, out_dir: Path) -> int:
    """Copy the three files and check them; returns the exit code."""
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"{out_dir} exists and is not empty; name a new or empty directory")
        return 1
    missing = [name for name in FILES if not (target_dir / name).is_file()]
    if missing:
        print(f"missing from {target_dir}: {', '.join(missing)}")
        return 1

    created = not out_dir.exists()
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        shutil.copyfile(target_dir / name, out_dir / name)

    problems = check_site(out_dir)
    if problems:
        for problem in problems:
            print(problem)
        for name in FILES:
            (out_dir / name).unlink(missing_ok=True)
        if created:
            out_dir.rmdir()
        return 1

    manifest = json.loads((out_dir / "manifest.json").read_text())
    print(f"site assembled in {out_dir}: {_counts(manifest)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    return assemble(args.target_dir, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
