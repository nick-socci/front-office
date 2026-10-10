"""Assemble the public dbt docs site from exactly three files, or refuse to.

Spec 0013 R1.3, R1.4. The dbt docs site is public and the ESPN league is private, so the
site is built by copying `index.html`, `manifest.json` and `catalog.json` out of dbt's
target directory by name (never a directory copy: target/ also holds run results and
compiled SQL), then checking the copies:

- the output holds exactly those three files;
- every catalog node and source says it came from the `ci` database (fixtures), not the
  real-season warehouse;
- no JSON key in the manifest or catalog is one of privacy.FORBIDDEN_KEYS;
- privacy.GUID matches nothing in index.html, nor in any key or string of the two JSON
  files other than `metadata.invocation_id` and `metadata.user_id`, dbt's own ids. The
  exemption is by location, not by value. A match is printed truncated, never whole;
- no object in the two JSON files repeats a key: parsing keeps only the last value of a
  repeated key, so an earlier one would be published unchecked.

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


# The only places a GUID may stand: dbt's own ids for the run and the installation.
# Paths are tuples of keys, so a single key spelled `metadata.invocation_id` is not one.
DBT_ID_PATHS = frozenset({("metadata", "invocation_id"), ("metadata", "user_id")})


def _guids(node: Any, path: tuple[str, ...] = ()) -> set[str]:
    """Every GUID in a parsed document's keys and strings, outside DBT_ID_PATHS.

    By location, not by value: dbt's run id repeated in a description is not exempt.
    """
    if isinstance(node, dict):
        found: set[str] = set()
        for key, value in node.items():
            found.update(GUID.findall(str(key)))
            found.update(_guids(value, (*path, str(key))))
        return found
    if isinstance(node, list):
        return set().union(*(_guids(item, (*path, "[]")) for item in node))
    if isinstance(node, str) and path not in DBT_ID_PATHS:
        return set(GUID.findall(node))
    return set()


def _load(text: str) -> tuple[Any, list[str]]:
    """A parsed JSON document, and every key that some object in it repeats."""
    repeated: list[str] = []

    def pairs_to_dict(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        seen: set[str] = set()
        for key, _ in pairs:
            if key in seen:
                repeated.append(key)
            seen.add(key)
        return dict(pairs)

    return json.loads(text, object_pairs_hook=pairs_to_dict), repeated


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
    parsed: dict[str, Any] = {}
    for name in ("manifest.json", "catalog.json"):
        parsed[name], repeated = _load(texts[name])
        for key in sorted(set(repeated)):
            shown = GUID.sub("<GUID>", key)
            problems.append(f"{name}: duplicate key {shown}, whose earlier value is unchecked")

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

    # The page itself is text, and nothing in it is exempt.
    found = {"index.html": set(GUID.findall(texts["index.html"]))}
    found.update({name: _guids(document) for name, document in parsed.items()})
    for name in FILES:
        for match in sorted(found[name]):
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
