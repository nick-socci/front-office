"""The daily pipeline as one Dagster code location (spec 0217, ADRs 0127 to 0131).

Why one function: `build_defs()` reads `FO_WAREHOUSE` to decide what `daily` selects (R3.5) and
which dbt target the manifest is parsed for, so a test can build the definitions under each
setting; `defs` is its result for the settings of the process, which is what
`dagster dev -m front_office_pipeline` and `dagster definitions validate` load.

`daily` selects every asset but `idmap_capture` (R4.2: it is materialized by hand until #218
gives it a cadence), and but `source_freshness` on BigQuery (R3.5: its filters are DuckDB SQL).
It runs in `in_process_executor`, so steps run one after another and the two fetches never hold
the landing zone's writer lock together (R1.4).
"""

from dagster import (
    AssetSelection,
    Definitions,
    define_asset_job,
    in_process_executor,
)
from dagster_dbt import DbtCliResource

from front_office_pipeline import assets, dbt_assets, settings


def build_defs() -> Definitions:
    manifest = dbt_assets.load_manifest(dbt_assets.manifest_target())
    dbt_definition = dbt_assets.build_dbt_assets(manifest)
    source_freshness = assets.source_freshness_asset(dbt_definition.keys)

    selection = AssetSelection.all() - AssetSelection.assets("idmap_capture")
    if settings.warehouse() == "bigquery":
        selection = selection - AssetSelection.assets("source_freshness")
    daily = define_asset_job("daily", selection=selection, executor_def=in_process_executor)
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
        jobs=[daily],
        resources={
            "dbt": DbtCliResource(
                project_dir=str(settings.DBT_DIR), profiles_dir=str(settings.DBT_DIR)
            )
        },
    )


defs = build_defs()
