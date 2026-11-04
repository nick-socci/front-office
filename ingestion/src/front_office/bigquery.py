"""The BigQuery side of the upload: the real `Warehouse` that `upload.upload` runs against.

Spec 0140; ADR 0119. It reads through the table read API (`tabledata.list`, which bills
nothing: R3.2) and never by a query, and it writes only by load jobs, plus the creation of the
`raw` dataset and of an empty table. The client library is imported inside the methods that
need it, never at module level, so that importing this module, and a dry run, need no
`bigquery` dependency group. The client is always built with the project named explicitly
(`bigquery.Client(project=…)`), never a gcloud default.

`column_from_api` is pure: it turns what the API reports for a field into the loader's own
`Column`, normalising the API's legacy type names, so the run compares schemas without the
client.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from front_office.capture_structures import Column

if TYPE_CHECKING:
    from google.cloud import bigquery

DATASET = "raw"
# The names the API reports for a type that the loader's `Column` spells another way.
LEGACY_TYPES = {"INTEGER": "INT64", "FLOAT": "FLOAT64", "BOOLEAN": "BOOL", "STRUCT": "RECORD"}
# What `stored` selects: a table's key columns and its file path, nothing else (R3.2).
STORED_FIELDS = ("source", "endpoint", "request_path", "request_key", "fetched_at", "file_path")


def column_from_api(
    name: str, field_type: str, mode: str | None, fields: Iterable[Any] = ()
) -> Column:
    """A `Column` from the parts of an API `SchemaField`: its legacy type names normalised
    (`INTEGER` is `INT64`, `FLOAT` is `FLOAT64`, `BOOLEAN` is `BOOL`, `STRUCT` is `RECORD`), a
    missing mode `NULLABLE`, and a RECORD's `fields` converted the same way. `fields` are
    objects with `name`, `field_type`, `mode` and `fields`."""
    return Column(
        name,
        LEGACY_TYPES.get(field_type.upper(), field_type.upper()),
        (mode or "NULLABLE").upper(),
        tuple(column_from_api(f.name, f.field_type, f.mode, f.fields) for f in fields),
    )


def _plain(value: Any) -> Any:
    """A value of a row as plain Python: a row or mapping as a dict, a list as a list."""
    if hasattr(value, "items"):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


class BigQueryWarehouse:
    """Every table lives in dataset `raw` of `project`."""

    def __init__(self, project: str, location: str = "US") -> None:
        from google.cloud import bigquery

        self.project = project
        self.location = location
        self.client = bigquery.Client(project=project, location=location)

    def _ref(self, table: str) -> str:
        return f"{self.project}.{DATASET}.{table}"

    def billing_enabled(self) -> bool:
        """Whether the project has a billing account linked. Read-only: this never creates,
        changes or removes one. `cloud-platform` is one of the scopes `getBillingInfo`
        accepts, and the one the BigQuery client's credentials already carry."""
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        response = AuthorizedSession(credentials).get(
            f"https://cloudbilling.googleapis.com/v1/projects/{self.project}/billingInfo",
            timeout=30,
        )
        response.raise_for_status()
        return bool(response.json().get("billingEnabled"))

    def columns(self, table: str) -> list[Column] | None:
        from google.api_core.exceptions import NotFound

        try:
            found = self.client.get_table(self._ref(table))
        except NotFound:
            return None
        return [column_from_api(f.name, f.field_type, f.mode, f.fields) for f in found.schema]

    def _ensure_dataset(self) -> None:
        from google.cloud import bigquery

        dataset = bigquery.Dataset(f"{self.project}.{DATASET}")
        dataset.location = self.location
        self.client.create_dataset(dataset, exists_ok=True)

    @staticmethod
    def _schema(columns: Iterable[Column]) -> list[bigquery.SchemaField]:
        from google.cloud import bigquery

        return [
            bigquery.SchemaField(
                column.name,
                column.type,
                mode=column.mode,
                fields=BigQueryWarehouse._schema(column.fields),
            )
            for column in columns
        ]

    def create(self, table: str, columns: list[Column]) -> None:
        """An empty table: no clustering, no partitioning (design, *Tables*)."""
        from google.cloud import bigquery

        self._ensure_dataset()
        self.client.create_table(bigquery.Table(self._ref(table), schema=self._schema(columns)))

    def stored(self, table: str) -> list[tuple[str, ...]]:
        """The key columns and file path of every row, by `tabledata.list` with those fields
        selected: it bills nothing, and it is never a query."""
        reference = self._ref(table)
        schema = self.client.get_table(reference).schema
        selected = [field for name in STORED_FIELDS for field in schema if field.name == name]
        return [
            tuple(str(row[name]) for name in STORED_FIELDS)
            for row in self.client.list_rows(reference, selected_fields=selected)
        ]

    def load(self, table: str, columns: list[Column], rows: Path, *, replace: bool) -> int:
        """One load job from the newline-delimited JSON file `rows`."""
        from google.cloud import bigquery

        self._ensure_dataset()
        config = bigquery.LoadJobConfig(
            schema=self._schema(columns),
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=(
                bigquery.WriteDisposition.WRITE_TRUNCATE
                if replace
                else bigquery.WriteDisposition.WRITE_APPEND
            ),
            create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED,
        )
        with rows.open("rb") as handle:
            job = self.client.load_table_from_file(handle, self._ref(table), job_config=config)
        job.result()
        return int(job.output_rows or 0)

    def rows(self, table: str) -> Iterator[dict[str, Any]]:
        """Every row, every column, by `tabledata.list`, as plain dicts and lists. The client
        library parses a JSON cell itself, at the top level and inside a RECORD
        (`CellDataParser.json_to_py`, `google/cloud/bigquery/_helpers.py`, `json.loads`), so
        the values are used as given: parsing them again would turn a JSON string that is
        itself JSON text into something else."""
        for row in self.client.list_rows(self._ref(table)):
            yield _plain(row)
