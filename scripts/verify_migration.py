"""Verify a landing-layout migration (spec 0029, R6.1, R6.2) against its journal.

Two subcommands, both exit non-zero on any difference:

  files  --manifest M --journal J --root R [--deleted LIST]
      M is `sha256sum` output taken before the migration, paths relative to the old root
      and starting `./`. Every line is mapped through the journal (`X.json` becomes
      `<new directory>/payload.json`, `X.meta.json` becomes `<new directory>/meta.json`);
      the mapped file must exist and hash to the manifest's value. A line whose old path is
      in LIST (one path per line, `data/raw/...` or relative) must be absent from the tree
      and counts as deleted. Every file under R must be accounted for by exactly one line.

  rows   --old-db OLD --new-db NEW --journal J --old-root-prefix P [--new-root-prefix Q]
      Every row of raw.api_responses must match between the two warehouses on the key
      (source, endpoint, request_path, request_key, fetched_at), `partitions` and `payload`,
      and the old row's file_path, mapped through the journal, must equal the new row's.
      File paths are stored as given to the loader: P is the old root as it was then (for
      example `data/raw`), Q the new root as it is now (default: P).

The journal must end `finished` for `files`. Both warehouses are attached read-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from front_office.landing import META_FILE, PAYLOAD_FILE
from warehouse_diff import attach, quote

KEY = ("source", "endpoint", "request_path", "request_key", "fetched_at")
SHOWN = 10


def read_journal(path: Path) -> tuple[dict[str, str], str | None]:
    """(old stem -> new directory, the last bracket's status), from `begin` records."""
    moves: dict[str, str] = {}
    status = None
    for line in path.read_text().split("\n")[:-1]:
        fields = line.split("\t")
        if fields[0] == "begin" and len(fields) == 3:
            moves[fields[1]] = fields[2]
        elif fields[0] == "start":
            status = "in progress"
        elif fields[0] == "finished":
            status = "migrated"
        elif fields[0] == "reversed":
            status = "reversed"
    return moves, status


def map_old_path(moves: dict[str, str], old: str) -> str | None:
    """Where the journal moved an old file (`X.json`, `X.meta.json`), or None."""
    if old.endswith(".meta.json"):
        directory = moves.get(old[: -len(".meta.json")])
        return f"{directory}/{META_FILE}" if directory is not None else None
    if old.endswith(".json"):
        directory = moves.get(old[: -len(".json")])
        return f"{directory}/{PAYLOAD_FILE}" if directory is not None else None
    return None


def normalise(path: str) -> str:
    path = path.strip()
    while path.startswith("./"):
        path = path[2:]
    return path


@dataclass
class Findings:
    problems: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        self.problems.append(text)

    def show(self) -> None:
        for text in self.problems[:SHOWN]:
            print(f"  {text}")
        if len(self.problems) > SHOWN:
            print(f"  ... and {len(self.problems) - SHOWN} more")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# -- files -----------------------------------------------------------------------------------


def parse_manifest(path: Path) -> list[tuple[str, str]]:
    entries = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition(" ")
        entries.append((digest, normalise(name.lstrip(" *"))))
    return entries


def verify_files(manifest: Path, journal: Path, root: Path, deleted: Path | None) -> int:
    moves, status = read_journal(journal)
    entries = parse_manifest(manifest)
    paths = {name for _digest, name in entries}
    findings = Findings()
    if status != "migrated":
        findings.add(f"the journal's last bracket is {status!r}, not finished")

    listed: set[str] = set()
    if deleted is not None:
        for raw in deleted.read_text().splitlines():
            entry = normalise(raw)
            if not entry:
                continue
            matches = {p for p in paths if entry == p or entry.endswith("/" + p)}
            if not matches:
                findings.add(f"listed as deleted but not in the manifest: {entry}")
            listed |= matches

    ok = deleted_ok = 0
    accounted: dict[str, str] = {}
    for digest, name in entries:
        target = map_old_path(moves, name)
        if name in listed:
            present = [
                p for p in (root / name, root / target if target else None) if p and p.exists()
            ]
            if present:
                findings.add(f"listed as deleted but present: {present[0]}")
            else:
                deleted_ok += 1
            continue
        if target is None:
            findings.add(f"unmapped: the journal never moved {name}")
            continue
        if target in accounted:
            findings.add(f"accounted for twice: {target} (from {name} and {accounted[target]})")
            continue
        accounted[target] = name
        found = root / target
        if not found.is_file():
            findings.add(f"missing: {target} (was {name})")
        elif sha256_of(found) != digest:
            findings.add(f"changed: {target} (was {name})")
        else:
            ok += 1

    under_root = [p for p in sorted(root.rglob("*")) if p.is_file()]
    unexpected = [p for p in under_root if str(p.relative_to(root)) not in accounted]
    for path in unexpected:
        findings.add(f"unexpected: {path.relative_to(root)} is in no manifest line")

    print(
        f"{len(entries)} manifest lines: {ok} verified, {deleted_ok} deleted as listed; "
        f"{len(under_root)} files under {root}, {len(unexpected)} unexpected; "
        f"{len(findings.problems)} problems"
    )
    findings.show()
    return 1 if findings.problems else 0


# -- raw rows --------------------------------------------------------------------------------


def verify_rows(
    old_db: Path,
    new_db: Path,
    journal: Path,
    old_prefix: str,
    new_prefix: str,
) -> int:
    if old_db.stem == new_db.stem:
        raise SystemExit("the two warehouse files need different names (they are attached by stem)")
    moves, _status = read_journal(journal)
    con = duckdb.connect()
    old, new = attach(con, old_db), attach(con, new_db)
    table = "raw.api_responses"
    on = " and ".join(f"o.{c} = n.{c}" for c in KEY)
    findings = Findings()

    both = con.execute(
        f"select {', '.join(f'o.{c}' for c in KEY)}, o.file_path, n.file_path, "
        "o.partitions::varchar = n.partitions::varchar, o.payload::varchar = n.payload::varchar "
        f"from {quote(old)}.{table} o join {quote(new)}.{table} n on {on} "
        "order by 1, 2, 3, 4, 5"
    ).fetchall()
    matched = changed = 0
    for *key, old_path, new_path, same_partitions, same_payload in both:
        label = "/".join(str(part) for part in key)
        if not (same_partitions and same_payload):
            # Text differs: it may still be the same JSON, spaced differently.
            same_partitions = same_partitions or same_json(
                con, old, new, table, on, key, "partitions"
            )
            same_payload = same_payload or same_json(con, old, new, table, on, key, "payload")
        if not same_partitions:
            findings.add(f"changed partitions: {label}")
        if not same_payload:
            findings.add(f"changed payload: {label}")
        expected = mapped_row_path(moves, old_path, old_prefix, new_prefix)
        if expected != new_path:
            findings.add(f"file_path does not map: {old_path} -> {new_path} (expected {expected})")
        if same_partitions and same_payload and expected == new_path:
            matched += 1
        else:
            changed += 1

    missing = con.execute(
        f"select {', '.join(f'o.{c}' for c in KEY)} from {quote(old)}.{table} o "
        f"anti join {quote(new)}.{table} n on {on}"
    ).fetchall()
    extra = con.execute(
        f"select {', '.join(f'n.{c}' for c in KEY)} from {quote(new)}.{table} n "
        f"anti join {quote(old)}.{table} o on {on}"
    ).fetchall()
    for row in missing:
        findings.add(f"missing from NEW: {'/'.join(map(str, row))}")
    for row in extra:
        findings.add(f"extra in NEW: {'/'.join(map(str, row))}")

    print(
        f"{matched} matched, {changed} changed, {len(missing)} missing, {len(extra)} extra "
        f"({len(both) + len(missing)} rows in OLD)"
    )
    findings.show()
    return 1 if findings.problems else 0


def same_json(
    con: duckdb.DuckDBPyConnection,
    old: str,
    new: str,
    table: str,
    on: str,
    key: list[object],
    column: str,
) -> bool:
    """Whether one row's column is the same JSON on both sides: the same types at every node
    (`true` is not `1`, `1` is not `1.0`), the same keys, the same array order. Python `==`
    on parsed values would equate those, so both sides are re-serialised canonically and the
    strings compared."""
    where = " and ".join(f"o.{c} = ?" for c in KEY)
    row = con.execute(
        f"select o.{column}::varchar, n.{column}::varchar from {quote(old)}.{table} o "
        f"join {quote(new)}.{table} n on {on} where {where}",
        key,
    ).fetchone()
    return row is not None and canonical(row[0]) == canonical(row[1])


def canonical(text: str) -> str:
    return json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))


def mapped_row_path(
    moves: dict[str, str], old_path: str, old_prefix: str, new_prefix: str
) -> str | None:
    """The old row's file_path as the journal moves it, under the new prefix."""
    prefix = old_prefix.rstrip("/") + "/"
    if not old_path.startswith(prefix):
        return None
    target = map_old_path(moves, old_path[len(prefix) :])
    return f"{new_prefix.rstrip('/')}/{target}" if target is not None else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    files = commands.add_parser("files", help="every file against the checksum manifest")
    files.add_argument("--manifest", type=Path, required=True)
    files.add_argument("--journal", type=Path, required=True)
    files.add_argument("--root", type=Path, required=True)
    files.add_argument("--deleted", type=Path, default=None)
    rows = commands.add_parser("rows", help="raw.api_responses, old warehouse against new")
    rows.add_argument("--old-db", type=Path, required=True)
    rows.add_argument("--new-db", type=Path, required=True)
    rows.add_argument("--journal", type=Path, required=True)
    rows.add_argument("--old-root-prefix", required=True)
    rows.add_argument("--new-root-prefix", default=None)
    args = parser.parse_args(argv)
    if args.command == "files":
        return verify_files(args.manifest, args.journal, args.root, args.deleted)
    new_prefix = args.new_root_prefix if args.new_root_prefix is not None else args.old_root_prefix
    return verify_rows(args.old_db, args.new_db, args.journal, args.old_root_prefix, new_prefix)


if __name__ == "__main__":
    sys.exit(main())
