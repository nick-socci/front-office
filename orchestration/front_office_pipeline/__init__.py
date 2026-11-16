# The daily pipeline as Dagster assets (spec 0217). `dagster definitions validate -m
# front_office_pipeline` loads this module; the assets are added to `defs` by later tasks.
from dagster import Definitions

defs = Definitions()
