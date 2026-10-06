"""Move a landing zone from the old layout to capture directories, by rename alone (ADR 0014).

Usage:  uv run python scripts/migrate_landing_layout.py ROOT [--dry-run] [--reverse]

Old layout: a payload `fetched_at=S.json` beside its sidecar `fetched_at=S.meta.json`.
New layout: a directory `fetched_at=S/` holding `payload.json` and `meta.json`.

Each capture moves in four steps, only ever mkdir and rename (no file is opened for
writing, so no file's contents, inode or mtime changes):

  1. mkdir  S.migrating/
  2. rename S.json       -> S.migrating/payload.json
  3. rename S.meta.json  -> S.migrating/meta.json
  4. rename S.migrating/ -> S/

Under the writer lock. The journal, `<ROOT>_migration/journal.tsv`, is append-only and
tab-separated, fsynced after every record; its directory is made git-ignored before the
first record, because the paths in it include the league id. Records: `start`;
`begin<TAB>stem<TAB>directory` before a capture's first rename; `done<TAB>stem` after its
last; `finished`; `reversed`. Stems and directories are relative to ROOT.

An interrupted run is resumed by running the script again: it first completes every
capture the journal shows begun and not done, working out from the files on disk how far
that capture got, then continues with the rest, in the same bracket. `--reverse` undoes
every capture of the latest bracket from whatever state it is in and appends `reversed`.

Anything that is not a usable old-layout pair (a payload with no sidecar, a sidecar that
does not describe its own path) is not touched and is listed at the end. A tree already in
the new layout is left alone and the journal is not changed.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from front_office.landing import (
    CAPTURE_PREFIX,
    JOURNAL_FILE,
    META_FILE,
    PAYLOAD_FILE,
    LandingLocked,
    LandingZone,
)

WORKING_SUFFIX = ".migrating"
SHOWN = 20


class MigrationError(Exception):
    """The migration cannot go on without a person looking; nothing further was changed."""


# The only three filesystem operations the migration performs. Named so a test can stop the
# run between any two of them, as a killed process would.


def _mkdir(path: Path) -> None:
    os.mkdir(path)  # noqa: PTH102


def _rename(source: Path, destination: Path) -> None:
    os.rename(source, destination)  # noqa: PTH104


def _rmdir(path: Path) -> None:
    os.rmdir(path)  # noqa: PTH106


# -- the journal -----------------------------------------------------------------------------


@dataclass
class JournalState:
    """What the journal says: its last bracket's status and the captures it began."""

    status: str | None = None  # "in progress", "migrated", "reversed" or None (no journal)
    begun: dict[str, str] = field(default_factory=dict)  # stem -> new directory
    done: set[str] = field(default_factory=set)


def read_journal(directory: Path) -> JournalState:
    state = JournalState()
    try:
        text = (directory / JOURNAL_FILE).read_text()
    except FileNotFoundError:
        return state
    for line in text.split("\n")[:-1]:  # a torn last line (no newline) is not a record
        fields = line.split("\t")
        record = fields[0]
        if record == "start":
            if state.status != "in progress":
                state.begun, state.done = {}, set()
            state.status = "in progress"
        elif record == "begin" and len(fields) == 3:
            state.begun[fields[1]] = fields[2]
            state.done.discard(fields[1])
        elif record == "done" and len(fields) == 2:
            state.done.add(fields[1])
        elif record == "finished":
            state.status = "migrated"
        elif record == "reversed":
            state.status = "reversed"
    return state


class Journal:
    """The append-only journal, opened (and its directory made git-ignored) on first use."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._fd: int | None = None

    def record(self, *fields: str) -> None:
        if self._fd is None:
            self.directory.mkdir(parents=True, exist_ok=True)
            (self.directory / ".gitignore").write_text("*\n")  # before the first record
            path = self.directory / JOURNAL_FILE
            torn = (
                path.exists() and path.stat().st_size > 0 and not path.read_bytes().endswith(b"\n")
            )
            self._fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            if torn:
                os.write(self._fd, b"\n")
        os.write(self._fd, ("\t".join(fields) + "\n").encode())
        os.fsync(self._fd)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


# -- finding the old-layout pairs ------------------------------------------------------------


def discover(zone: LandingZone) -> tuple[list[Path], list[Path]]:
    """(usable old-layout stems, everything else loose under the root), both sorted.

    Directories named `fetched_at=...` are already capture directories (or a leftover
    working directory, which resumption owns) and are not searched.
    """
    stems: list[Path] = []
    left: list[Path] = []
    for folder, dirs, names in os.walk(zone.root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(CAPTURE_PREFIX))
        held = set(names)
        claimed: set[str] = set()
        for name in sorted(held):
            if not name.endswith(".json") or name.endswith(".meta.json"):
                continue
            stem = Path(folder) / name[: -len(".json")]
            sidecar = f"{stem.name}.meta.json"
            if sidecar in held and zone.old_layout_problem(stem) is None:
                stems.append(stem)
                claimed |= {name, sidecar}
        left += [Path(folder) / name for name in sorted(held - claimed)]
    return sorted(stems), sorted(left)


def paths_of(stem: Path) -> tuple[Path, Path, Path]:
    """(payload, sidecar, working directory) for an old-layout stem."""
    return (
        stem.with_name(f"{stem.name}.json"),
        stem.with_name(f"{stem.name}.meta.json"),
        stem.with_name(f"{stem.name}{WORKING_SUFFIX}"),
    )


def holds_only_a_capture(directory: Path) -> bool:
    return {entry.name for entry in directory.iterdir()} <= {PAYLOAD_FILE, META_FILE}


# -- the four steps, and from any state ------------------------------------------------------


def complete(stem: Path, final: Path) -> None:
    """Finish moving one capture, whatever state it is in. Idempotent.

    The states and what each does next:
      nothing moved           mkdir, rename, rename, rename
      working dir, empty      rename, rename, rename
      payload moved only      rename the sidecar, rename the directory
      both moved              rename the directory
      final directory exists  nothing (the last rename happened, `done` was not written)
    """
    payload, sidecar, working = paths_of(stem)
    if final.exists():
        if working.exists() or payload.exists() or sidecar.exists():
            raise MigrationError(
                f"{final} exists while parts of the same capture are elsewhere; "
                "not guessing which is right"
            )
        if sorted(entry.name for entry in final.iterdir()) != [META_FILE, PAYLOAD_FILE]:
            raise MigrationError(f"{final} exists and is not this capture's completed move")
        return
    if not working.exists():
        _mkdir(working)
    for old, name in ((payload, PAYLOAD_FILE), (sidecar, META_FILE)):
        target = working / name
        if old.exists():
            if target.exists():
                raise MigrationError(f"both {old} and {target} exist; not overwriting")
            _rename(old, target)
        elif not target.exists():
            raise MigrationError(f"{old} is nowhere to be found (not in {working} either)")
    _rename(working, final)


def undo(stem: Path, final: Path) -> None:
    """Put one capture back as two loose files, from whatever state it is in. Idempotent."""
    payload, sidecar, working = paths_of(stem)
    if final.exists():
        if working.exists():
            raise MigrationError(f"both {final} and {working} exist; not guessing")
        if not holds_only_a_capture(final):
            raise MigrationError(f"{final} holds more than a capture's two files")
        _rename(final, working)
    if working.exists():
        for old, name in ((payload, PAYLOAD_FILE), (sidecar, META_FILE)):
            held = working / name
            if held.exists():
                if old.exists():
                    raise MigrationError(f"both {old} and {held} exist; not overwriting")
                _rename(held, old)
        if any(working.iterdir()):
            raise MigrationError(f"{working} holds something other than the capture's files")
        _rmdir(working)
    if not (payload.exists() and sidecar.exists()):
        raise MigrationError(f"after undoing, {stem} is missing its payload or its sidecar")


# -- the commands ----------------------------------------------------------------------------


def relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def report_left(left: list[Path], root: Path) -> None:
    if not left:
        print("left behind: 0 items")
        return
    print(f"left behind (not touched): {len(left)} items")
    for path in left[:SHOWN]:
        print(f"  {relative(root, path)}")
    if len(left) > SHOWN:
        print(f"  ... and {len(left) - SHOWN} more")


def dry_run(zone: LandingZone) -> int:
    state = read_journal(zone.migration_dir)
    stems, left = discover(zone)
    pending = (
        [s for s in state.begun if s not in state.done] if state.status == "in progress" else []
    )
    if pending:
        print(f"a migration is in progress: {len(pending)} begun captures would be completed first")
    print(f"would migrate {len(stems)} captures")
    for stem in stems[:5]:
        print(f"  {relative(zone.root, stem)}")
    if len(stems) > 5:
        print(f"  ... and {len(stems) - 5} more")
    report_left(left, zone.root)
    return 0


def migrate(zone: LandingZone) -> int:
    root = zone.root
    state = read_journal(zone.migration_dir)
    journal = Journal(zone.migration_dir)
    try:
        resumed = 0
        if state.status == "in progress":
            for stem_rel, new_rel in state.begun.items():
                if stem_rel not in state.done:
                    complete(root / stem_rel, root / new_rel)
                    journal.record("done", stem_rel)
                    resumed += 1
        stems, left = discover(zone)
        for stem in stems:
            if stem.exists():
                raise MigrationError(f"{stem} exists; it would be overwritten. Nothing moved.")
        if not stems and state.status != "in progress":
            print("nothing to migrate: no old-layout captures found")
            report_left(left, root)
            return 0
        if state.status != "in progress":
            journal.record("start")
        for stem in stems:
            stem_rel = relative(root, stem)
            journal.record("begin", stem_rel, stem_rel)
            complete(stem, stem)
            journal.record("done", stem_rel)
        journal.record("finished")
    finally:
        journal.close()
    print(f"migrated {len(stems)} captures (completed {resumed} begun earlier)")
    report_left(left, root)
    return 0


def reverse(zone: LandingZone) -> int:
    root = zone.root
    state = read_journal(zone.migration_dir)
    if state.status is None:
        raise MigrationError(
            f"no journal at {zone.migration_dir / JOURNAL_FILE}; nothing to reverse"
        )
    if state.status == "reversed":
        print("already reversed; nothing to do")
        return 0
    journal = Journal(zone.migration_dir)
    try:
        for stem_rel, new_rel in state.begun.items():
            undo(root / stem_rel, root / new_rel)
        journal.record("reversed")
    finally:
        journal.close()
    print(f"reversed {len(state.begun)} captures")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", type=Path, help="the landing root, e.g. data/raw")
    parser.add_argument("--dry-run", action="store_true", help="report; change nothing")
    parser.add_argument("--reverse", action="store_true", help="undo the journal's latest bracket")
    args = parser.parse_args(argv)
    if args.dry_run and args.reverse:
        parser.error("--dry-run and --reverse cannot be combined")
    zone = LandingZone(args.root)
    if not zone.root.is_dir():
        print(f"error: {zone.root} is not a directory", file=sys.stderr)
        return 1
    try:
        if args.dry_run:
            return dry_run(zone)
        with zone.writer_lock():
            return reverse(zone) if args.reverse else migrate(zone)
    except (MigrationError, LandingLocked) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
