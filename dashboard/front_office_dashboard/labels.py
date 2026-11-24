"""Column tooltips from the dbt descriptions (spec 0232 R3.2, amended).

A mart column is shown under its dbt name, and its description from
`dbt/models/marts/_marts__models.yml` is the tooltip. The YAML ships in the image; the manifest
does not. A column with no description has no tooltip: nothing is invented.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any

import streamlit as st
import yaml

MARTS_YAML = Path(__file__).resolve().parents[2] / "dbt" / "models" / "marts" / "_marts__models.yml"

Descriptions = dict[str, dict[str, str]]


@cache
def _default() -> Descriptions:
    return descriptions(MARTS_YAML)


def descriptions(path: Path | None = None) -> Descriptions:
    """`{model: {column: description}}`, each description on one line. Columns without one are
    left out."""
    document = yaml.safe_load((path or MARTS_YAML).read_text())
    found: Descriptions = {}
    for model in document.get("models") or []:
        columns: dict[str, str] = {}
        for column in model.get("columns") or []:
            text = column.get("description")
            if text:
                columns[column["name"]] = " ".join(str(text).split())
        found[model["name"]] = columns
    return found


def column_config(
    columns: Iterable[str], models: Iterable[str], found: Descriptions | None = None
) -> dict[str, Any]:
    """`st.column_config` entries for `columns`: the help is the description from the first of
    `models` (in order) that describes the column. A column none describes gets no entry."""
    found = _default() if found is None else found
    order = list(models)
    config: dict[str, Any] = {}
    for column in columns:
        for model in order:
            text = found.get(model, {}).get(column)
            if text:
                config[column] = st.column_config.Column(help=text)
                break
    return config
