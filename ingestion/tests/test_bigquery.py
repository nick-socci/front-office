"""The BigQuery side of the upload that needs no BigQuery (spec 0140, ADR 0119).

`column_from_api` is pure. The rest of the module is exercised by task 8's real run.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

import pytest

from front_office.bigquery import column_from_api
from front_office.capture_structures import Column


@dataclass
class Field:
    """What of an API SchemaField `column_from_api` reads."""

    name: str
    field_type: str
    mode: str | None = "NULLABLE"
    fields: tuple[Field, ...] = ()


@pytest.mark.parametrize(
    ("api", "ours"),
    [
        ("INTEGER", "INT64"),
        ("INT64", "INT64"),
        ("FLOAT", "FLOAT64"),
        ("BOOLEAN", "BOOL"),
        ("STRUCT", "RECORD"),
        ("RECORD", "RECORD"),
        ("STRING", "STRING"),
        ("JSON", "JSON"),
    ],
)
def test_a_legacy_type_name_becomes_the_one_the_loader_uses(api: str, ours: str) -> None:
    """Catches a schema comparison that calls a table changed because the API says INTEGER
    where the structure says INT64, which would demand a rebuild on every run (R4.1)."""
    assert column_from_api("c", api, "NULLABLE", ()) == Column("c", ours)


def test_a_missing_mode_is_nullable() -> None:
    """Catches None reaching the comparison, where Column's mode is never None."""
    assert column_from_api("c", "STRING", None, ()).mode == "NULLABLE"
    assert column_from_api("c", "STRING", "REPEATED", ()).mode == "REPEATED"


def test_a_record_is_converted_to_its_depth() -> None:
    """Catches the normalisation stopping at the first level of a nested RECORD."""
    inner = Field("n", "INTEGER", None)
    middle = Field("m", "STRUCT", "REPEATED", (inner, Field("j", "JSON", "NULLABLE")))
    column = column_from_api("top", "RECORD", "NULLABLE", (middle,))
    assert column == Column(
        "top",
        "RECORD",
        "NULLABLE",
        (Column("m", "RECORD", "REPEATED", (Column("n", "INT64"), Column("j", "JSON"))),),
    )


def test_importing_the_module_needs_no_google() -> None:
    """Catches a module-level import of the client, which a dry run could not survive
    without the bigquery group (R7.1)."""
    script = (
        "import sys\n"
        "import front_office.bigquery\n"
        "clients = ('google.cloud.bigquery', 'google.auth', 'google.api_core')\n"
        "print([m for m in sys.modules if m.startswith(clients)])\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert done.stdout.strip() == "[]"
