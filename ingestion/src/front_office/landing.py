"""The landing zone: raw API responses saved to disk, exactly as they arrived.

Nothing here interprets a payload. That is deliberate: parsing happens in dbt, so a
parsing mistake costs a rebuild rather than a re-download of the whole season.

Layout:  data/raw/{source}/{endpoint}/{partition=value}/fetched_at={stamp}/
holding exactly two files: payload.json (the response, as it arrived) and meta.json
(the request that produced it, plus the payload's size and SHA-256).

A capture is a directory published by one rename (ADR 0014): it is visible complete or
not at all. `LandingZone.check` is the single definition of "committed", and every reader
asks it, directly or through `committed`, `has_landed` and `iter_landed`.
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import logging
import math
import os
import shutil
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

PayloadType = Mapping[str, Any] | list[Any]

PAYLOAD_FILE = "payload.json"
META_FILE = "meta.json"
CAPTURE_PREFIX = "fetched_at="
TEMP_MARKER = ".tmp-"
# Raised by a reader that races a sweep: the entry vanished between listing and reading.
VANISHED = (FileNotFoundError, NotADirectoryError)
JOURNAL_FILE = "journal.tsv"
SWEEP_FLOOR = 50
SWEEP_FRACTION = 0.01
LOCK_WAIT_S = 2.0
LOCK_RETRY_S = 0.1


class LandingCollision(Exception):
    """A capture's final directory already exists; nothing was written."""


class LandingLocked(Exception):
    """Another process holds the writer lock."""


class NotMigrated(Exception):
    """The landing zone is not wholly in the directory layout; the migration must finish."""


class SweepTooLarge(Exception):
    """A sweep would move more than the limit allows; nothing was moved."""


class PayloadNotJson(ValueError):
    """A committed capture's payload.json does not parse as JSON."""


@dataclass(frozen=True)
class ScannedFile:
    """One entry found in the landing zone, classified by `LandingZone.scan`.

    kind is one of:
      committed  a `fetched_at=` directory that passes the shallow check
      temp       a directory whose name contains `.tmp-`: an interrupted write
      invalid    a `fetched_at=` directory that fails the shallow check (or is empty)
      loose      a file that is not inside a capture or temporary directory
      empty      any other directory with nothing in it
    `path` is the directory for committed/invalid/temp/empty, the file for loose.
    """

    kind: str
    path: Path


class Capture:
    """A committed capture: its directory, its parsed sidecar, and a lazy payload."""

    def __init__(self, directory: Path, meta: Mapping[str, Any]) -> None:
        self.directory = directory
        self.meta = meta

    @property
    def payload_path(self) -> Path:
        return self.directory / PAYLOAD_FILE

    @property
    def payload(self) -> Any:
        """The parsed payload, read on each access. Raises PayloadNotJson naming the file."""
        path = self.payload_path
        try:
            return json.loads(path.read_bytes())
        except ValueError as error:
            raise PayloadNotJson(f"{path} is not valid JSON: {error}") from error


class LandedResponse:
    """What `iter_landed` yields: `path` is the capture's payload.json."""

    def __init__(self, capture: Capture) -> None:
        self.capture = capture

    @property
    def path(self) -> Path:
        return self.capture.payload_path

    @property
    def meta(self) -> Mapping[str, Any]:
        return self.capture.meta

    @property
    def payload(self) -> Any:
        return self.capture.payload


class LandingZone:
    """Reads and writes the raw landing zone under a root directory."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def quarantine_root(self) -> Path:
        """Where the sweep moves what is not a capture: beside the root, never inside it."""
        return self.root.with_name(self.root.name + "_quarantine")

    @property
    def lock_path(self) -> Path:
        return self.root.with_name(self.root.name + ".lock")

    @property
    def migration_dir(self) -> Path:
        """Holds the migration's journal (`journal.tsv`); written by the migration script."""
        return self.root.with_name(self.root.name + "_migration")

    @staticmethod
    def request_key(params: Mapping[str, Any] | None) -> str:
        """A canonical string for a request's parameters, independent of their order."""
        if not params:
            return ""
        return "&".join(f"{key}={params[key]}" for key in sorted(params))

    @staticmethod
    def request_path(url: str | None) -> str:
        """The URL's path alone (no scheme, host or query), without a trailing slash."""
        if not url:
            return ""
        return urlsplit(url).path.rstrip("/")

    def path_for(
        self,
        *,
        source: str,
        endpoint: str,
        partitions: Mapping[str, Any],
        name: str,
    ) -> Path:
        """The capture directory for `name` (e.g. `fetched_at=<stamp>`)."""
        path = self.root / source / endpoint
        for key in partitions:
            path = path / f"{key}={partitions[key]}"
        return path / name

    # -- writing --------------------------------------------------------------------------

    def write(
        self,
        *,
        source: str,
        endpoint: str,
        partitions: Mapping[str, Any],
        name: str,
        payload: PayloadType,
        request: Mapping[str, Any],
        fetched_at: str,
    ) -> Path:
        """Land a capture as a directory, published by one rename. Returns the directory.

        The files are built in a temporary directory beside the final one, so a crash or a
        full disk never leaves anything a reader could mistake for a capture. If the final
        directory exists, empty or not, nothing is written and LandingCollision is raised:
        a rename onto an empty directory would silently replace it.
        """
        final = self.path_for(source=source, endpoint=endpoint, partitions=partitions, name=name)
        if final.exists():
            raise LandingCollision(f"capture already exists: {final}")
        tmp = final.with_name(f"{final.name}{TEMP_MARKER}{os.getpid()}")

        body = json.dumps(payload).encode()
        meta = {
            "source": source,
            "endpoint": endpoint,
            "partitions": dict(partitions),
            "url": request.get("url"),
            "params": dict(request.get("params") or {}),
            "request_key": self.request_key(request.get("params")),
            "fetched_at": fetched_at,
            "payload_bytes": len(body),
            "payload_sha256": hashlib.sha256(body).hexdigest(),
        }

        # Folders this call will create, outermost first; the root itself is never one.
        made: list[Path] = []
        for folder in (final.parent, *final.parent.parents):
            if folder.exists() or folder == self.root or self.root not in folder.parents:
                break
            made.insert(0, folder)

        published = False
        created = False
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
            tmp.mkdir()
            created = True
            (tmp / PAYLOAD_FILE).write_bytes(body)
            (tmp / META_FILE).write_text(json.dumps(meta, indent=2))
            try:
                os.rename(tmp, final)  # noqa: PTH104 - the one publishing step, named on purpose
            except OSError as error:
                if error.errno in (errno.ENOTEMPTY, errno.EEXIST):
                    raise LandingCollision(f"capture already exists: {final}") from error
                raise
            published = True
        finally:
            if created and not published:
                shutil.rmtree(tmp, ignore_errors=True)
            if not published:
                for folder in reversed(made):
                    try:
                        folder.rmdir()
                    except OSError:
                        break  # not empty (or gone): everything above is in use too
        return final

    # -- the one definition of committed --------------------------------------------------

    def check(self, capture_dir: Path, deep: bool = False) -> str | None:
        """None when `capture_dir` is a committed capture, else the reason it is not.

        Shallow (the default) lists the directory, reads meta.json and stats payload.json;
        it never reads the payload. `deep` also parses the payload and, where the sidecar
        records one, verifies its SHA-256.
        """
        try:
            return self._check(capture_dir, deep)
        except VANISHED:
            return "vanished while being read"

    def _check(self, capture_dir: Path, deep: bool) -> str | None:
        name = capture_dir.name
        if not name.startswith(CAPTURE_PREFIX) or len(name) == len(CAPTURE_PREFIX):
            return f"not named {CAPTURE_PREFIX}<stamp>"
        if TEMP_MARKER in name:
            return "a temporary directory"
        if not capture_dir.is_dir():
            return "not a directory"
        held = sorted(entry.name for entry in capture_dir.iterdir())
        if held != [META_FILE, PAYLOAD_FILE]:
            return f"holds {held}, not exactly {PAYLOAD_FILE} and {META_FILE}"

        try:
            meta = json.loads((capture_dir / META_FILE).read_bytes())
        except ValueError:
            return f"{META_FILE} is not valid JSON"
        reason = _sidecar_problem(meta)
        if reason:
            return reason
        reason = self._disagreement(capture_dir, meta)
        if reason:
            return reason

        payload = capture_dir / PAYLOAD_FILE
        size = payload.stat().st_size
        recorded = meta.get("payload_bytes")
        if recorded is not None and (
            not isinstance(recorded, int) or isinstance(recorded, bool) or recorded != size
        ):
            return f"payload is {size} bytes, sidecar records {recorded!r}"
        if not deep:
            return None

        body = payload.read_bytes()
        try:
            json.loads(body)
        except ValueError:
            return f"{PAYLOAD_FILE} is not valid JSON"
        digest = meta.get("payload_sha256")
        if digest is not None and hashlib.sha256(body).hexdigest() != digest:
            return "payload does not match its recorded SHA-256"
        return None

    def _disagreement(self, capture_dir: Path, meta: Mapping[str, Any]) -> str | None:
        """The sidecar must describe the path the capture is at."""
        expected = self.path_for(
            source=meta["source"],
            endpoint=meta["endpoint"],
            partitions=meta["partitions"],
            name=f"{CAPTURE_PREFIX}{meta['fetched_at']}",
        )
        if expected != capture_dir:
            try:
                shown: Path | str = expected.relative_to(self.root)
            except ValueError:
                shown = expected
            return f"sidecar describes {shown}"
        return None

    # -- reading --------------------------------------------------------------------------

    def committed(
        self,
        source: str | None = None,
        endpoint: str | None = None,
        partitions: Mapping[str, Any] | None = None,
    ) -> Iterator[Capture]:
        """Yield every committed capture, sorted by path.

        With `partitions` (which needs source and endpoint) only that entity's folder is
        examined, and not folders nested below it.
        """
        if partitions is not None:
            if source is None or endpoint is None:
                raise ValueError("partitions needs source and endpoint")
            folder = self.path_for(
                source=source, endpoint=endpoint, partitions=partitions, name="-"
            ).parent
            candidates = self._capture_dirs(folder, recurse=False)
        else:
            base = self.root
            if source is not None:
                base = base / source
                if endpoint is not None:
                    base = base / endpoint
            candidates = self._capture_dirs(base, recurse=True)
        for directory in candidates:
            if self.check(directory) is not None:
                continue
            try:
                meta = json.loads((directory / META_FILE).read_bytes())
            except (*VANISHED, ValueError):
                continue
            yield Capture(directory, meta)

    @staticmethod
    def _capture_dirs(folder: Path, *, recurse: bool) -> Iterator[Path]:
        """`fetched_at=` directories under `folder`, in path order; never descends into one."""
        try:
            entries = sorted(folder.iterdir())
        except VANISHED:
            return
        for entry in entries:
            if TEMP_MARKER in entry.name or not entry.is_dir():
                continue
            if entry.name.startswith(CAPTURE_PREFIX):
                yield entry
            elif recurse:
                yield from LandingZone._capture_dirs(entry, recurse=True)

    def has_landed(self, *, source: str, endpoint: str, partitions: Mapping[str, Any]) -> bool:
        """True when the entity's folder holds at least one committed capture."""
        return any(
            True for _ in self.committed(source=source, endpoint=endpoint, partitions=partitions)
        )

    def iter_landed(
        self, *, source: str | None = None, endpoint: str | None = None
    ) -> Iterator[LandedResponse]:
        """Yield committed captures only, newest-named last, optionally by source/endpoint.

        Each yields `.path` (the capture's payload.json), `.meta`, and `.payload`, which is
        parsed on access so that a reader of one capture does not parse them all.
        """
        for capture in self.committed(source=source, endpoint=endpoint):
            yield LandedResponse(capture)

    def scan(self, *, source: str | None = None) -> Iterator[ScannedFile]:
        """Classify every entry under the root (or one source), sorted by path.

        A folder that leads to at least one entry is structure and is not reported; the
        contents of a capture or temporary directory are not reported separately.
        """
        base = self.root if source is None else self.root / source
        if not base.is_dir():
            return
        yield from self._scan_folder(base, is_root=True)

    def _scan_folder(self, folder: Path, *, is_root: bool) -> Iterator[ScannedFile]:
        try:
            entries = sorted(folder.iterdir())
        except VANISHED:
            return
        if not entries and not is_root:
            yield ScannedFile(kind="empty", path=folder)
            return
        for entry in entries:
            if not entry.is_dir():
                yield ScannedFile(kind="loose", path=entry)
            elif TEMP_MARKER in entry.name:
                yield ScannedFile(kind="temp", path=entry)
            elif entry.name.startswith(CAPTURE_PREFIX):
                kind = "committed" if self.check(entry) is None else "invalid"
                yield ScannedFile(kind=kind, path=entry)
            else:
                yield from self._scan_folder(entry, is_root=False)

    # -- the layout interlock -------------------------------------------------------------

    def layout_problem(self) -> str | None:
        """Why the landing zone is not wholly in the directory layout, or None.

        It is not when the migration journal's last bracket is in progress or reversed, or
        when any old-layout pair (`X.json` beside `X.meta.json`) is found, journal or not.
        Journal records are tab-separated, one per line, the first field the type:
        `start`, `begin<TAB>old<TAB>new`, `done<TAB>old`, `finished`, `reversed`.
        """
        state = None
        journal = self.migration_dir / JOURNAL_FILE
        try:
            text = journal.read_text()
        except FileNotFoundError:
            text = ""
        for line in text.splitlines():
            record = line.split("\t", 1)[0]
            if record == "start":
                state = "in progress"
            elif record == "finished":
                state = "migrated"
            elif record == "reversed":
                state = "reversed"
        fix = "run scripts/migrate_landing_layout.py to completion first"
        if state in ("in progress", "reversed"):
            return f"the layout migration is {state} ({journal}); {fix}"
        for folder, _dirs, names in os.walk(self.root):
            held = set(names)
            for name in sorted(held):
                is_payload = name.endswith(".json") and not name.endswith(".meta.json")
                if is_payload and name[: -len(".json")] + ".meta.json" in held:
                    return f"old-layout capture pair found at {Path(folder) / name}; {fix}"
        return None

    # -- sweeping -------------------------------------------------------------------------

    def _file_count(self) -> int:
        return sum(len(names) for _folder, _dirs, names in os.walk(self.root))

    def sweep_limit(self) -> int:
        """The most items a sweep may move without `force`: the larger of 50 and 1% of files."""
        return max(SWEEP_FLOOR, math.ceil(SWEEP_FRACTION * self._file_count()))

    def _plan(self, *, deep: bool) -> list[tuple[str, Path]]:
        """Everything a sweep would move, worked out on paper: the complete plan.

        Each non-committed entry; with `deep`, committed captures failing the deep check;
        and each folder left with nothing in it once those are gone. Where a folder and
        everything in it are in the plan, only the folder is listed.
        """
        flagged: dict[Path, str] = {}
        for scanned in self.scan():
            if scanned.kind != "committed":
                flagged[scanned.path] = scanned.kind
            elif deep and self.check(scanned.path, deep=True) is not None:
                flagged[scanned.path] = "corrupt"

        def visit(folder: Path) -> tuple[bool, list[tuple[str, Path]]]:
            """(whether `folder` ends up empty, the plan entries beneath it)."""
            emptied = True
            entries: list[tuple[str, Path]] = []
            for entry in sorted(folder.iterdir()):
                if entry in flagged:
                    entries.append((flagged[entry], entry))
                elif entry.is_dir() and not (
                    entry.name.startswith(CAPTURE_PREFIX) or TEMP_MARKER in entry.name
                ):
                    gone, below = visit(entry)
                    if gone:
                        entries.append(("empty", entry))
                    else:
                        entries += below
                        emptied = False
                else:
                    emptied = False
            return emptied, entries

        if not self.root.is_dir():
            return []
        _gone, entries = visit(self.root)
        return [(kind, path.relative_to(self.root)) for kind, path in entries]

    def sweep(
        self,
        run_stamp: str,
        *,
        dry_run: bool = False,
        deep: bool = False,
        force: bool = False,
    ) -> list[tuple[str, Path]]:
        """Move whatever is not a committed capture to the quarantine. Returns the plan.

        The plan is (kind, path relative to the root) and is the same list that is limited,
        reported by a dry run and moved. Raises NotMigrated if the landing zone is not
        wholly in the directory layout, and SweepTooLarge (moving nothing) when the plan
        exceeds `sweep_limit()` and `force` is false; a dry run only reports.
        """
        problem = self.layout_problem()
        if problem:
            raise NotMigrated(problem)
        plan = self._plan(deep=deep)
        if dry_run or not plan:
            return plan
        limit = self.sweep_limit()
        if len(plan) > limit and not force:
            first = ", ".join(str(path) for _kind, path in plan[:3])
            raise SweepTooLarge(
                f"sweep would move {len(plan)} items, over the limit of {limit} "
                f"(the larger of {SWEEP_FLOOR} and 1% of the files under {self.root}); "
                f"first: {first}. Nothing was moved; inspect with `front-office repair "
                "--dry-run`, then `--force` if it is right."
            )

        self.quarantine_root.mkdir(parents=True, exist_ok=True)
        (self.quarantine_root / ".gitignore").write_text("*\n")
        run_dir = self.quarantine_root / run_stamp
        suffix = 1
        while True:
            try:
                run_dir.mkdir()
                break
            except FileExistsError:
                suffix += 1
                run_dir = self.quarantine_root / f"{run_stamp}-{suffix}"
        for kind, relative in plan:
            destination = run_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.rename(self.root / relative, destination)  # noqa: PTH104 - a move, named on purpose
            logger.warning("quarantined %s %s -> %s", kind, relative, destination)
        return plan

    # -- the writer lock ------------------------------------------------------------------

    @contextmanager
    def writer_lock(self) -> Iterator[None]:
        """Hold the exclusive writer lock (`flock`) for the block, or raise LandingLocked.

        The operating system releases it when the process ends, however it ends. It waits
        up to two seconds, because a reader's `writer_active` probe holds the lock for an
        instant.
        """
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            deadline = time.monotonic() + LOCK_WAIT_S
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LandingLocked(
                            f"another writer holds {self.lock_path}; wait for it to finish"
                        ) from None
                    time.sleep(LOCK_RETRY_S)
            yield
        finally:
            os.close(descriptor)  # closing releases the lock

    def writer_active(self) -> bool:
        """True when a writer holds the lock. Never waits, never creates the lock file."""
        try:
            descriptor = os.open(self.lock_path, os.O_RDONLY)
        except FileNotFoundError:
            return False
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            return False
        finally:
            os.close(descriptor)


def _sidecar_problem(meta: Any) -> str | None:
    """Why a parsed sidecar lacks the fields a capture needs, or None."""
    if not isinstance(meta, dict):
        return "sidecar is not an object"
    for field in ("source", "endpoint", "fetched_at", "url"):
        if not isinstance(meta.get(field), str) or not meta[field]:
            return f"sidecar {field} is missing or not a non-empty string"
    if not isinstance(meta.get("request_key"), str):
        return "sidecar request_key is missing or not a string"
    if not isinstance(meta.get("partitions"), dict):
        return "sidecar partitions is missing or not a mapping"
    return None
