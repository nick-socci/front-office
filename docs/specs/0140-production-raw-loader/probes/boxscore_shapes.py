"""Spec 0140's probe: what the two boxscore models bill and return per raw-table shape.

Kept with the spec so that its claims can be rerun. It is evidence, not part of the build.

Two shapes of `mlb/boxscore`, each reduced to the view's declared structure:

    projected  today's columns, `payload` a JSON value holding only the declared fields
    typed      the declared structure as columns, a map as an array of key-value structs,
               which is the shape bigquery__fo_json_parse_value gives; JSON leaves stay JSON

    export   write both as newline-delimited JSON under --out
    load     load both into `probe_140` by load jobs (free)
    measure  dry-run the compiled models against today's table and both shapes, then run them
             against both shapes and compare the rows with the populated `staging_139` tables
    drop     delete `probe_140`

Compiled SQL comes from a BigQuery target whose models point at `staging_139`.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from google.cloud import bigquery

from front_office.landing import LandingZone

DATASET = "probe_140"
LOCATION = "US"
KEYS = ("source", "endpoint", "request_path", "request_key", "fetched_at", "file_path")
COMPILED = "models/staging/mlb"
VIEW = "models/staging/raw/stg_raw__mlb_boxscore.sql"
MODELS = ("stg_mlb__pitching_game_logs", "stg_mlb__batting_game_logs")
BASE = "staging_139"
PLAYER = {
    "person": "JSON",
    "position": "JSON",
    "battingOrder": "JSON",
    "gameStatus": "JSON",
    "stats": {"batting": "JSON", "pitching": "JSON"},
}
SIDE = {"team": {"id": "BIGINT"}, "teamStats": {"batting": "JSON"}, "players": {"__map__": PLAYER}}
STRUCTURE = {"teams": {"home": SIDE, "away": SIDE}}


def reduce(value: Any, part: Any, *, typed: bool) -> Any:
    """`value` holding only what `part` declares; a map becomes key-value rows if `typed`."""
    if isinstance(part, str):
        return value
    if not isinstance(value, dict):
        return None
    if "__map__" in part:
        reduced = {k: reduce(v, part["__map__"], typed=typed) for k, v in value.items()}
        return [{"key": k, "value": v} for k, v in reduced.items()] if typed else reduced
    return {k: reduce(value[k], p, typed=typed) for k, p in part.items() if k in value}


def field(name: str, part: Any) -> bigquery.SchemaField:
    if isinstance(part, str):
        return bigquery.SchemaField(name, "JSON" if part == "JSON" else "INT64")
    if "__map__" in part:
        entry = (bigquery.SchemaField("key", "STRING"), field("value", part["__map__"]))
        return bigquery.SchemaField(name, "RECORD", mode="REPEATED", fields=entry)
    return bigquery.SchemaField(name, "RECORD", fields=tuple(field(k, p) for k, p in part.items()))


def export(raw_root: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    zone = LandingZone(raw_root)
    written = 0
    with (
        (out / "projected.ndjson").open("w") as projected,
        (out / "typed.ndjson").open("w") as typed,
    ):
        for landed in zone.iter_landed(source="mlb", endpoint="boxscore"):
            meta, payload = landed.meta, landed.payload
            keys = {
                "source": meta["source"],
                "endpoint": meta["endpoint"],
                "request_path": LandingZone.request_path(meta["url"]),
                "request_key": meta["request_key"],
                "fetched_at": meta["fetched_at"],
                "file_path": landed.path.relative_to(zone.root).as_posix(),
                "partitions": meta["partitions"],
            }
            kept = reduce(payload, STRUCTURE, typed=False)
            projected.write(json.dumps({**keys, "payload": kept}) + "\n")
            typed.write(json.dumps({**keys, **reduce(payload, STRUCTURE, typed=True)}) + "\n")
            written += 1
    print(f"exported {written} captures")
    for name in ("projected", "typed"):
        print(name, round((out / f"{name}.ndjson").stat().st_size / 1e9, 3), "GB of text")


def load(client: bigquery.Client, out: Path) -> None:
    dataset = bigquery.Dataset(f"{client.project}.{DATASET}")
    dataset.location = LOCATION
    client.create_dataset(dataset, exists_ok=True)
    keys = [bigquery.SchemaField(name, "STRING") for name in KEYS]
    keys.append(bigquery.SchemaField("partitions", "JSON"))
    schemas = {
        "projected": [*keys, bigquery.SchemaField("payload", "JSON")],
        "typed": [*keys, field("teams", STRUCTURE["teams"])],
    }
    for name, schema in schemas.items():
        config = bigquery.LoadJobConfig(
            schema=schema,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        with (out / f"{name}.ndjson").open("rb") as handle:
            job = client.load_table_from_file(
                handle, f"{client.project}.{DATASET}.{name}", job_config=config
            )
        job.result()
        table = client.get_table(f"{client.project}.{DATASET}.{name}")
        print(f"{name}: {table.num_rows} rows, {table.num_bytes / 1e9:.3f} GB stored")


def views(client: bigquery.Client, compiled: Path) -> None:
    """A capture view per shape: the real view's parse over the projected table, and a plain
    selection over the typed one, which needs no parse."""
    project = client.project
    parse = (compiled / VIEW).read_text()
    parse = parse.replace(
        f"`{project}`.`raw`.`api_responses`", f"`{project}`.`{DATASET}`.`projected`"
    )
    client.query(
        f"create or replace view `{project}`.`{DATASET}`.`view_projected` as {parse}"
    ).result()
    client.query(
        f"create or replace view `{project}`.`{DATASET}`.`view_typed` as "
        "select source, endpoint, request_path, request_key, fetched_at, partitions, "
        f"file_path, teams from `{project}`.`{DATASET}`.`typed`"
    ).result()


def model_sql(client: bigquery.Client, compiled: Path, model: str, shape: str | None) -> str:
    sql = (compiled / COMPILED / f"{model}.sql").read_text()
    if shape is None:
        return sql
    view = f"`{client.project}`.`{BASE}`.`stg_raw__mlb_boxscore`"
    if view not in sql:
        raise SystemExit(f"{model}: the compiled SQL does not read {view}")
    return sql.replace(view, f"`{client.project}`.`{DATASET}`.`view_{shape}`")


def measure(client: bigquery.Client, compiled: Path) -> None:
    views(client, compiled)
    dry = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    for model in MODELS:
        for shape in (None, "projected", "typed"):
            job = client.query(model_sql(client, compiled, model, shape), job_config=dry)
            print(f"dry {model} {shape or 'today'}: {job.total_bytes_processed / 1e9:.3f} GB")
    for model in MODELS:
        for shape in ("projected", "typed"):
            target = f"{client.project}.{DATASET}.{model}_{shape}"
            config = bigquery.QueryJobConfig(
                destination=target,
                write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
                use_query_cache=False,
            )
            started = time.monotonic()
            job = client.query(model_sql(client, compiled, model, shape), job_config=config)
            job.result(timeout=1800)
            print(
                f"run {model} {shape}: {job.total_bytes_billed / 1e9:.3f} GB billed, "
                f"{job.slot_millis / 1000:.0f} slot-s, {time.monotonic() - started:.0f} s wall"
            )
            base = f"{client.project}.{BASE}.{model}"
            for left, right, label in ((base, target, "base only"), (target, base, "probe only")):
                rows = client.query(
                    "select count(*) as n from ("
                    f"select to_json_string(a) as j from `{left}` as a except distinct "
                    f"select to_json_string(b) from `{right}` as b)"
                ).result()
                print(f"  {label}: {next(iter(rows)).n}")
            count = next(iter(client.query(f"select count(*) as n from `{target}`").result())).n
            print(f"  rows: {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=("export", "load", "measure", "drop"))
    parser.add_argument("--project")
    parser.add_argument("--raw-root", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("data/spec140"))
    parser.add_argument("--compiled", type=Path, help="target/compiled/front_office of a bq run")
    args = parser.parse_args()
    if args.step == "export":
        export(args.raw_root, args.out)
        return 0
    if not re.fullmatch(r"[a-z0-9-]+", args.project or ""):
        parser.error("--project is required")
    client = bigquery.Client(project=args.project, location=LOCATION)
    if args.step == "load":
        load(client, args.out)
    elif args.step == "measure":
        measure(client, args.compiled)
    else:
        client.delete_dataset(f"{args.project}.{DATASET}", delete_contents=True, not_found_ok=True)
        print(f"deleted {DATASET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
