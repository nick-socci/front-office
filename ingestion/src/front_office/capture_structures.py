"""The declared structures of the heavy capture views, as the loader reads them.

A heavy endpoint goes up to BigQuery as the structure its capture view declares, one column
per top-level field (spec 0140, ADRs 0117 and 0118). The structures are written once, in
`dbt/macros/capture_structures.sql`, and read from there, so that the view and the loader
cannot hold two (R5.1).

Three things are read from a structure:

- `columns`: the BigQuery columns it gives, the types the view gives on BigQuery today. An
  object is a RECORD, a list REPEATED, a map (`{"__map__": X}`) a REPEATED RECORD of `key`
  and `value`, and a leaf its type: BIGINT as INT64, VARCHAR as STRING, JSON as JSON (R1.2).
- `reduce`: a payload holding only what the structure declares, each map still an object
  whose keys are keys, so that the privacy check reads the document as it landed (R6.3).
- `as_columns`: a reduced payload as the row a load job takes, each map now key-value rows.

The reduction gives a declared field the payload lacks what the view gives it: null, or an
empty list for a list or a map, since a REPEATED column holds no null (R5.2). A value that does
not fit is refused, never defaulted (R5.3): the refusal names the path and the kind of value
found, never the value.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from front_office import privacy

STRUCTURES_FILE = Path(__file__).resolve().parents[3] / "dbt" / "macros" / "capture_structures.sql"
MAP = "__map__"
# The leaves a structure may hold, and the BigQuery type each is stored as. The BigQuery
# parse also takes DOUBLE and BOOLEAN; no structure declares one, and the loader has no
# reduction for them, so a structure that does is refused when it is read.
LEAVES = {"BIGINT": "INT64", "VARCHAR": "STRING", "JSON": "JSON"}
INT64_MIN, INT64_MAX = -(2**63), 2**63 - 1

# One branch of fo_capture_structure: its condition, and the structure set inside it.
_BRANCH = re.compile(r"(?:if|elif) source_name == '([a-z_]+)' and endpoint == '([a-z_]+)' -%}")
_SET = re.compile(r"{% set structure %}(.*?){% endset %}", re.S)


class StructureUnreadable(Exception):
    """The macro file does not hold structures the loader can read. Nothing was sent."""


class StructureMismatch(ValueError):
    """A payload does not fit its declared structure. Names the path, never the value."""

    def __init__(self, path: str, problem: str) -> None:
        # A map's keys are data and appear in the path; one could be an account id.
        self.path = privacy.GUID.sub("<guid>", path)
        self.problem = problem
        super().__init__(f"at {self.path}: {problem}")


@dataclass(frozen=True)
class Column:
    """A BigQuery column, described without the client library: `mode` is NULLABLE or
    REPEATED, and `fields` are a RECORD's columns."""

    name: str
    type: str
    mode: str = "NULLABLE"
    fields: tuple[Column, ...] = ()


def read_structures(path: Path = STRUCTURES_FILE) -> dict[tuple[str, str], dict[str, Any]]:
    """Each (source, endpoint) of fo_capture_structure, with its structure parsed. Raises
    StructureUnreadable unless every branch sets exactly one structure, a JSON object whose
    every part the loader can store."""
    text = path.read_text()
    branches = list(_BRANCH.finditer(text))
    if not branches:
        raise StructureUnreadable(f"{path}: no branch of fo_capture_structure found")
    structures: dict[tuple[str, str], dict[str, Any]] = {}
    for number, branch in enumerate(branches):
        end = branches[number + 1].start() if number + 1 < len(branches) else len(text)
        sets = _SET.findall(text, branch.end(), end)
        pair = (branch.group(1), branch.group(2))
        if len(sets) != 1:
            raise StructureUnreadable(f"{path}: {pair} sets {len(sets)} structures, not one")
        if pair in structures:
            raise StructureUnreadable(f"{path}: {pair} is declared twice")
        try:
            structure = json.loads(sets[0])
        except ValueError as error:
            raise StructureUnreadable(f"{path}: {pair} is not JSON: {error}") from None
        if not isinstance(structure, dict) or not structure or MAP in structure:
            raise StructureUnreadable(f"{path}: {pair} is not an object of fields")
        for field, part in structure.items():
            _column(field, part, f"{pair} $.{field}")
        structures[pair] = structure
    return structures


def columns(structure: dict[str, Any]) -> list[Column]:
    """The columns of a structure's top-level fields, in its order."""
    return [_column(field, part, f"$.{field}") for field, part in structure.items()]


def _is_map(part: Any) -> bool:
    return isinstance(part, dict) and len(part) == 1 and MAP in part


def _column(name: str, part: Any, where: str) -> Column:
    if isinstance(part, str):
        if part not in LEAVES:
            raise StructureUnreadable(f"{where}: the loader has no form for the type {part}")
        return Column(name, LEAVES[part])
    if _is_map(part):
        value = _column("value", part[MAP], f"{where}.{MAP}")
        return Column(name, "RECORD", "REPEATED", (Column("key", "STRING"), value))
    if isinstance(part, dict) and part and MAP not in part:
        inner = tuple(_column(field, p, f"{where}.{field}") for field, p in part.items())
        return Column(name, "RECORD", fields=inner)
    if isinstance(part, list) and len(part) == 1:
        element = _column(name, part[0], f"{where}[]")
        if element.mode == "REPEATED":
            # BigQuery has no list of lists; a list of maps would be one.
            raise StructureUnreadable(f"{where}: a list whose element is a list or a map")
        return Column(name, element.type, "REPEATED", element.fields)
    raise StructureUnreadable(f"{where}: not a leaf, a list of one part, a map or an object")


def _kind(value: Any) -> str:
    """What sort of value was found, for a message: never the value itself."""
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    return "text"


def reduce(payload: Any, structure: dict[str, Any]) -> dict[str, Any]:
    """`payload` holding only the declared fields, every declared field present, each map an
    object. Raises StructureMismatch for a value that does not fit."""
    if not isinstance(payload, dict):
        raise StructureMismatch("$", f"an object was declared, {_kind(payload)} found")
    return {
        field: _reduce(payload.get(field), part, f"$.{field}") for field, part in structure.items()
    }


def _reduce(value: Any, part: Any, path: str) -> Any:
    if isinstance(part, str):
        return _leaf(value, part, path)
    if isinstance(part, list):
        if value is None:
            return []
        if not isinstance(value, list):
            raise StructureMismatch(path, f"a list was declared, {_kind(value)} found")
        kept = []
        for index, item in enumerate(value):
            if item is None:
                # A REPEATED column holds no null: BigQuery would refuse the whole job.
                raise StructureMismatch(f"{path}[{index}]", "a null in a list")
            kept.append(_reduce(item, part[0], f"{path}[{index}]"))
        return kept
    if _is_map(part):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise StructureMismatch(path, f"a map was declared, {_kind(value)} found")
        return {key: _reduce(item, part[MAP], f"{path}.{key}") for key, item in value.items()}
    if value is None:
        return None
    if not isinstance(value, dict):
        raise StructureMismatch(path, f"an object was declared, {_kind(value)} found")
    return {
        field: _reduce(value.get(field), inner, f"{path}.{field}") for field, inner in part.items()
    }


def _leaf(value: Any, kind: str, path: str) -> Any:
    if value is None or kind == "JSON":
        return value
    whole = isinstance(value, int) and not isinstance(value, bool)
    if kind == "BIGINT":
        if isinstance(value, float) and value.is_integer():
            value, whole = int(value), True
        if not whole or not INT64_MIN <= value <= INT64_MAX:
            raise StructureMismatch(path, f"a whole number was declared, {_kind(value)} found")
        return value
    # VARCHAR. A whole number is stored as its digits, as lax_string reads it and as DuckDB
    # reads it into a VARCHAR (the league `id`, C7). A fraction or a boolean is refused: its
    # text as written in the file is gone once parsed, and none has been seen (Amendments).
    if isinstance(value, str):
        return value
    if whole:
        return str(value)
    raise StructureMismatch(path, f"text was declared, {_kind(value)} found")


def as_columns(reduced: dict[str, Any], structure: dict[str, Any]) -> dict[str, Any]:
    """A reduced payload as a load job's row: each map a list of `key`/`value` objects, in
    the document's order."""
    return {field: _as_column(reduced[field], part) for field, part in structure.items()}


def _as_column(value: Any, part: Any) -> Any:
    if isinstance(part, str) or value is None:
        return value
    if isinstance(part, list):
        return [_as_column(item, part[0]) for item in value]
    if _is_map(part):
        return [{"key": key, "value": _as_column(item, part[MAP])} for key, item in value.items()]
    return {field: _as_column(value[field], inner) for field, inner in part.items()}
