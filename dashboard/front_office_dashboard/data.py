"""The app's one way to read the extract (spec 0232, ADR 0147).

`query(name, **params)` runs `queries/<name>.sql` on the extract, opened read-only for that one
query and closed after it. Parameters are bound by name (`$season`); no query text is ever built
from a value. A result is cached on the query, its parameters and the extract's inode and
modification time: the daily publish is a rename, so a new extract is a new inode and misses.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[2]
QUERIES = Path(__file__).resolve().parent / "queries"
DEFAULT_EXTRACT = REPO_ROOT / "data" / "dashboard" / "extract.duckdb"


def extract_path() -> Path:
    """`FO_DASHBOARD_EXTRACT` if set (an absolute path), else the repository's own."""
    named = os.environ.get("FO_DASHBOARD_EXTRACT")
    return Path(named) if named else DEFAULT_EXTRACT


@st.cache_data(show_spinner=False)
def _run(
    name: str, params: dict[str, Any], extract_ino: int, extract_mtime_ns: int
) -> pd.DataFrame:
    # The inode and the time are in the signature only: they are the cache's key.
    sql = (QUERIES / f"{name}.sql").read_text()
    con = duckdb.connect(str(extract_path()), read_only=True)
    try:
        return con.execute(sql, params).df()
    finally:
        con.close()


def query(name: str, /, **params: Any) -> pd.DataFrame:
    """The rows of `queries/<name>.sql` with `params` bound, as a DataFrame."""
    stat = extract_path().stat()
    return _run(name, params, stat.st_ino, stat.st_mtime_ns)
