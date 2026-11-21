"""The daily pipeline as one Dagster code location (spec 0217, ADRs 0127 to 0131).

Why one function: `build_defs()` reads `FO_WAREHOUSE` to decide which dbt target the manifest is
parsed for, so a test can build the definitions under each setting; `defs` is its result for the
settings of the process, which is what `dagster dev -m front_office_pipeline` and
`dagster definitions validate` load.

`daily` selects every asset but `idmap_capture` (R4.2: the `idmap` job runs it, on its own weekly
schedule, spec 0218), `source_freshness` included on both warehouses (spec 0219 R4.2: its
filters are chosen by target type, ADR 0143). Three run-status sensors ping healthchecks.io when
`daily` or `idmap` ends (`sensors.py`). `daily` runs in `in_process_executor`, so steps run one
after another and the two fetches never hold the landing zone's writer lock together (R1.4).
"""

from dagster import (
    AssetSelection,
    Definitions,
    define_asset_job,
    in_process_executor,
)
from dagster_dbt import DbtCliResource

from front_office_pipeline import assets, dbt_assets, schedules, sensors, settings


def build_defs() -> Definitions:
    manifest = dbt_assets.load_manifest(dbt_assets.manifest_target())
    dbt_definition = dbt_assets.build_dbt_assets(manifest)
    source_freshness = assets.source_freshness_asset(dbt_definition.keys)

    selection = AssetSelection.all() - AssetSelection.assets("idmap_capture")
    daily = define_asset_job("daily", selection=selection, executor_def=in_process_executor)
    idmap = define_asset_job(
        "idmap",
        selection=AssetSelection.assets("idmap_capture"),
        executor_def=in_process_executor,
    )
    return Definitions(
        assets=[
            assets.mlb_captures,
            assets.espn_captures,
            assets.espn_matchup_days,
            assets.idmap_capture,
            assets.raw_in_warehouse,
            dbt_definition,
            source_freshness,
        ],
        jobs=[daily, idmap],
        sensors=sensors.run_sensors([daily, idmap]),
        schedules=[
            schedules.daily_schedule(schedules.daily_cron()),
            schedules.idmap_schedule(schedules.IDMAP_CRON),
        ],
        resources={
            "dbt": DbtCliResource(
                project_dir=str(settings.DBT_DIR), profiles_dir=str(settings.DBT_DIR)
            )
        },
    )


defs = build_defs()
