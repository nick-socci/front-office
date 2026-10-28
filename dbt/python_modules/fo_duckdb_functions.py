"""The lineup solver as a DuckDB SQL function, registered by a dbt-duckdb plugin (ADR 0103).

Why this exists: on BigQuery the solver is a Python UDF declared in dbt/functions/_functions.yml.
DuckDB has no such declaration, so the same file (dbt/functions/solve_lineup_period.py) is
registered here on every connection dbt opens, and one SQL model calls it on both warehouses.
A dbt plugin is a class dbt-duckdb builds from the profile's `plugins:` list; its
`configure_connection` runs on each new connection.

The function exists only on dbt's connections, not in the warehouse file: a view calling it
would fail for anyone who opens the database outside dbt. The model that calls it must
therefore be a table. The types below are the DuckDB spelling of the YAML's BigQuery
signature, field for field and in the same order; a pytest compares the two (spec 0137, R6.3).

`null_handling="special"` hands a NULL argument to the function as None: a league with no
start limit passes a null `start_limit`, and the default would return NULL without a call.

DuckDB tries to import pandas on every value it converts for a Python function. pandas is in
the dev group for that alone: without it the failed import, not the solve, takes most of the
node's time (#201).
"""

import duckdb
from dbt.adapters.duckdb.plugins import BasePlugin
from duckdb import list_type, struct_type
from duckdb.sqltypes import BIGINT, BOOLEAN, DATE, DOUBLE, VARCHAR

from solve_lineup_period import solve_lineup_period

NAME = "solve_lineup_period"
ARGUMENTS = [
    ("team", VARCHAR),
    ("matchup_period", BIGINT),
    (
        "options",
        list_type(
            struct_type(
                {
                    "scoring_date": DATE,
                    "player_id": BIGINT,
                    "slot_id": BIGINT,
                    "role": VARCHAR,
                    "value": DOUBLE,
                    "is_actual": BOOLEAN,
                    "is_start": BOOLEAN,
                }
            )
        ),
    ),
    (
        "slots",
        list_type(struct_type({"slot_id": BIGINT, "role": VARCHAR, "count": BIGINT})),
    ),
    ("start_limit", DOUBLE),
]
RETURNS = list_type(struct_type({"scoring_date": DATE, "player_id": BIGINT, "slot_id": BIGINT}))


class Plugin(BasePlugin):
    def configure_connection(self, conn: duckdb.DuckDBPyConnection) -> None:
        conn.create_function(
            NAME,
            solve_lineup_period,
            [argument_type for _, argument_type in ARGUMENTS],
            RETURNS,
            null_handling="special",
        )
