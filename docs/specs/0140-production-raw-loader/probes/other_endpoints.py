"""Spec 0140's probe, second part: typed tables for the other heavy endpoints, and tables of
their own for two endpoints small enough to show what a shared table's blocks cost.

Kept with the spec so that its claims can be rerun. It is evidence, not part of the build.
Writes into the same scratch dataset as boxscore_shapes.py; `drop` there deletes it.

    uv run --group bigquery python <this> --project "$FO_BQ_PROJECT" --compiled <bq compiled>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from google.cloud import bigquery

from front_office.landing import LandingZone

sys.path.insert(0, "scripts")
from spike_load_bigquery import project_matchup_day  # noqa: E402

DATASET = "probe_140"
BASE = "staging_139"
KEYS = ("source", "endpoint", "request_path", "request_key", "fetched_at", "file_path")
STRUCTURES = dict(
    zip(
        ("roster", "matchup_days", "boxscore", "schedule"),
        re.findall(
            r"{% set structure %}(.*?){% endset %}",
            Path("dbt/macros/capture_structures.sql").read_text(),
            re.S,
        ),
        strict=True,
    )
)
# (source, endpoint, shape, the models that read its capture view)
ENDPOINTS = (
    (
        "espn",
        "roster",
        "typed",
        ("stg_espn__roster_entries", "stg_espn__roster_entry_slots", "stg_espn__player_game_stats"),
    ),
    ("espn", "matchup_days", "typed", ("stg_espn__matchup_days", "stg_espn__matchup_player_lines")),
    ("mlb", "schedule", "typed", ("stg_mlb__games",)),
    ("idmap", "player_id_map", "json", ("stg_idmap__players",)),
)
COERCED: dict[str, int] = {}


def scalar(value: Any, kind: str) -> Any:
    """A declared leaf as BigQuery's lax_int64 and lax_string read it. Counted when it changes."""
    if value is None or kind == "JSON":
        return value
    if kind == "VARCHAR":
        if isinstance(value, str):
            return value
        COERCED["to text"] = COERCED.get("to text", 0) + 1
        return json.dumps(value)
    if isinstance(value, bool) or not isinstance(value, int):
        COERCED["from non-integer"] = COERCED.get("from non-integer", 0) + 1
        return int(value) if isinstance(value, (int, float)) and value == int(value) else None
    return value


def reduce(value: Any, part: Any) -> Any:
    if isinstance(part, str):
        return scalar(value, part)
    if isinstance(part, list):
        if not isinstance(value, list):
            return []
        return [reduce(item, part[0]) for item in value]
    if not isinstance(value, dict):
        return [] if "__map__" in part else None
    if "__map__" in part:
        return [{"key": k, "value": reduce(v, part["__map__"])} for k, v in value.items()]
    return {k: reduce(value.get(k), p) for k, p in part.items() if k in value}


def field(name: str, part: Any) -> bigquery.SchemaField:
    if isinstance(part, str):
        kind = {"JSON": "JSON", "VARCHAR": "STRING", "BIGINT": "INT64"}[part]
        return bigquery.SchemaField(name, kind)
    if isinstance(part, list):
        inner = field(name, part[0])
        return bigquery.SchemaField(name, inner.field_type, mode="REPEATED", fields=inner.fields)
    if "__map__" in part:
        entry = (bigquery.SchemaField("key", "STRING"), field("value", part["__map__"]))
        return bigquery.SchemaField(name, "RECORD", mode="REPEATED", fields=entry)
    return bigquery.SchemaField(name, "RECORD", fields=tuple(field(k, p) for k, p in part.items()))


def export_and_load(client: bigquery.Client, zone: LandingZone, out: Path, spec: tuple) -> str:
    source, endpoint, shape, _ = spec
    structure = json.loads(STRUCTURES[endpoint]) if shape == "typed" else None
    path = out / f"{endpoint}.ndjson"
    count = 0
    with path.open("w") as handle:
        for landed in zone.iter_landed(source=source, endpoint=endpoint):
            meta, payload = landed.meta, landed.payload
            if endpoint == "matchup_days":
                payload = project_matchup_day(payload)
            row = {
                "source": meta["source"],
                "endpoint": meta["endpoint"],
                "request_path": LandingZone.request_path(meta["url"]),
                "request_key": meta["request_key"],
                "fetched_at": meta["fetched_at"],
                "file_path": landed.path.relative_to(zone.root).as_posix(),
                "partitions": meta["partitions"],
            }
            if structure:
                row.update(reduce(payload, structure))
            else:
                row["payload"] = payload
            handle.write(json.dumps(row) + "\n")
            count += 1
    schema = [bigquery.SchemaField(name, "STRING") for name in KEYS]
    schema.append(bigquery.SchemaField("partitions", "JSON"))
    if structure:
        schema += [field(k, p) for k, p in structure.items()]
    else:
        schema.append(bigquery.SchemaField("payload", "JSON"))
    name = f"table_{endpoint}"
    config = bigquery.LoadJobConfig(
        schema=schema,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    target = f"{client.project}.{DATASET}.{name}"
    with path.open("rb") as handle:
        client.load_table_from_file(handle, target, job_config=config).result()
    table = client.get_table(target)
    print(
        f"{source}/{endpoint}: {count} captures, {path.stat().st_size / 1e9:.3f} GB text, "
        f"{table.num_rows} rows, {table.num_bytes / 1e9:.3f} GB stored",
        flush=True,
    )
    columns = ", ".join(f.name for f in schema)
    return f"select {columns} from `{target}`"


def compare(client: bigquery.Client, model: str, sql_text: str, view: str, select: str) -> None:
    project = client.project
    old = f"`{project}`.`{BASE}`.`stg_raw__{view}`"
    if old not in sql_text:
        raise SystemExit(f"{model}: compiled SQL does not read {old}")
    sql_text = sql_text.replace(old, f"({select})")
    target = f"{project}.{DATASET}.result_{model}"
    config = bigquery.QueryJobConfig(
        destination=target,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        use_query_cache=False,
    )
    started = time.monotonic()
    job = client.query(sql_text, job_config=config)
    job.result(timeout=1800)
    print(
        f"run {model}: {job.total_bytes_billed / 1e9:.3f} GB billed, "
        f"{job.slot_millis / 1000:.0f} slot-s, {time.monotonic() - started:.0f} s wall",
        flush=True,
    )
    base = f"{project}.{BASE}.{model}"
    for left, right, label in ((base, target, "base only"), (target, base, "probe only")):
        rows = client.query(
            f"select count(*) as n from (select to_json_string(a) as j from `{left}` as a "
            f"except distinct select to_json_string(b) from `{right}` as b)"
        ).result()
        print(f"  {label}: {next(iter(rows)).n}", flush=True)
    counts = client.query(
        f"select (select count(*) from `{base}`) as b, (select count(*) from `{target}`) as t"
    ).result()
    row = next(iter(counts))
    print(f"  rows: base {row.b}, probe {row.t}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", required=True)
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/spec140"))
    parser.add_argument("--compiled", type=Path, required=True)
    args = parser.parse_args()
    client = bigquery.Client(project=args.project, location="US")
    zone = LandingZone(args.raw_root)
    for spec in ENDPOINTS:
        source, endpoint, _, models = spec
        select = export_and_load(client, zone, args.out, spec)
        print("  leaves coerced:", COERCED, flush=True)
        COERCED.clear()
        for model in models:
            kind = {"stg_espn": "espn", "stg_mlb_": "mlb", "stg_idma": "idmap"}[model[:8]]
            text = (args.compiled / "models/staging" / kind / f"{model}.sql").read_text()
            compare(client, model, text, f"{source}_{endpoint}", select)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
