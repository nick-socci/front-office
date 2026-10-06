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
import hashlib
import json
import os
import shutil
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

PayloadType = Mapping[str, Any] | list[Any]

PAYLOAD_FILE = "payload.json"
META_FILE = "meta.json"
CAPTURE_PREFIX = "fetched_at="
TEMP_MARKER = ".tmp-"
# Raised by a reader that races a sweep: the entry vanished between listing and reading.
VANISHED = (FileNotFoundError, NotADirectoryError)


class LandingCollision(Exception):
    """A capture's final directory already exists; nothing was written."""


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
        final.parent.mkdir(parents=True, exist_ok=True)
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

        published = False
        created = False
        try:
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
