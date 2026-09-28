"""The landing zone: raw API responses saved to disk, exactly as they arrived.

Nothing here interprets a payload. That is deliberate: parsing happens in dbt, so a
parsing mistake costs a rebuild rather than a re-download of the whole season.

Layout:  data/raw/{source}/{endpoint}/{partition=value}/{name}.json
with a {name}.meta.json sidecar recording the request that produced it.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PayloadType = Mapping[str, Any] | list[Any]


@dataclass(frozen=True)
class LandedResponse:
    """One landed file, paired with the metadata sidecar describing its request."""

    path: Path
    payload: Any
    meta: Mapping[str, Any]


@dataclass(frozen=True)
class ScannedFile:
    """One file found in the landing zone, classified without reading it.

    kind is one of:
      committed     a payload with its sidecar beside it
      payload_only  a payload with no sidecar: landed outside the ingestion package, or
                    a write interrupted between the two renames
      sidecar_only  a sidecar whose payload is missing
      temp          a temporary file left behind by an interrupted write
      other         anything else: nothing the ingestion package writes
    """

    kind: str
    path: Path


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

    def path_for(
        self,
        *,
        source: str,
        endpoint: str,
        partitions: Mapping[str, Any],
        name: str,
    ) -> Path:
        path = self.root / source / endpoint
        for key in partitions:
            path = path / f"{key}={partitions[key]}"
        return path / f"{name}.json"

    def has_landed(
        self,
        *,
        source: str,
        endpoint: str,
        partitions: Mapping[str, Any],
        name: str,
    ) -> bool:
        return self.path_for(
            source=source, endpoint=endpoint, partitions=partitions, name=name
        ).exists()

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
        """Land a payload and its sidecar atomically.

        Both files are written to temporary names and renamed into place, so a crash or a
        full disk can never leave a half-written file that a later run would treat as
        valid landed data.
        """
        path = self.path_for(source=source, endpoint=endpoint, partitions=partitions, name=name)
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "source": source,
            "endpoint": endpoint,
            "partitions": dict(partitions),
            "url": request.get("url"),
            "params": dict(request.get("params") or {}),
            "request_key": self.request_key(request.get("params")),
            "fetched_at": fetched_at,
        }
        self._atomic_write(path, json.dumps(payload))
        self._atomic_write(path.with_suffix(".meta.json"), json.dumps(meta, indent=2))
        return path

    def iter_landed(
        self, *, source: str | None = None, endpoint: str | None = None
    ) -> Iterator[LandedResponse]:
        """Yield landed responses, newest-named last, optionally filtered by source/endpoint."""
        base = self.root
        if source is not None:
            base = base / source
            if endpoint is not None:
                base = base / endpoint
        if not base.exists():
            return
        for path in sorted(base.rglob("*.json")):
            if path.name.endswith(".meta.json"):
                continue
            meta_path = path.with_suffix(".meta.json")
            meta: Mapping[str, Any] = (
                json.loads(meta_path.read_text()) if meta_path.exists() else {}
            )
            yield LandedResponse(path=path, payload=json.loads(path.read_text()), meta=meta)

    def scan(self, *, source: str | None = None) -> Iterator[ScannedFile]:
        """Classify every file under the root (or one source) by name alone, sorted by path.

        For a payload, `path` is the payload; for a sidecar-only entry, the sidecar.
        """
        base = self.root if source is None else self.root / source
        if not base.exists():
            return
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            if ".json.tmp-" in path.name:
                yield ScannedFile(kind="temp", path=path)
            elif path.name.endswith(".meta.json"):
                payload = path.with_name(path.name.removesuffix(".meta.json") + ".json")
                if not payload.exists():
                    yield ScannedFile(kind="sidecar_only", path=path)
            elif path.suffix == ".json":
                paired = path.with_suffix(".meta.json").exists()
                yield ScannedFile(kind="committed" if paired else "payload_only", path=path)
            else:
                yield ScannedFile(kind="other", path=path)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}")
        try:
            tmp.write_text(text)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
