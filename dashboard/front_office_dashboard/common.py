"""What every page shares: the league-season picker and the table display (spec 0232 R3)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

import pandas as pd
import streamlit as st

from front_office_dashboard import data, freshness, labels
from front_office_dashboard import format as fmt

BANNER = "Extract made"
STALE = (
    "The data may be stale: the extract is over 36 hours old in season. Check the daily run "
    "(runbook: *When an alert arrives*)."
)
FLAG_HELP = (
    "Marked where has_unverified_inputs or is_unvalued is true: the row rests on an input the "
    "build could not verify, or has no value."
)


def plain(value: Any) -> Any:
    """A Python scalar for a numpy one, so it is a stable cache key and a bindable parameter."""
    return value.item() if hasattr(value, "item") else value


def league_season(key: str) -> tuple[str, str, int]:
    """The league-season picker (R3.1): `(platform, league_id, season)`, defaulting to the
    latest season in the extract (the query lists them newest first)."""
    found = data.query("league_seasons").to_dict("records")
    if not found:
        st.info("The extract holds no league-season yet.")
        st.stop()
    index = st.selectbox(
        "League and season",
        range(len(found)),
        index=0,
        format_func=lambda i: f"{found[i]['league_id']} · {found[i]['season']}",
        key=f"{key}_league_season",
    )
    chosen = found[index]
    return str(chosen["platform"]), str(chosen["league_id"]), int(chosen["season"])


def show(
    frame: pd.DataFrame, models: Iterable[str], extra_help: dict[str, str] | None = None
) -> None:
    """A table of mart columns: rows with an unverified input or no value marked (R3.4), each
    column under its dbt name with its description as the tooltip (R3.2)."""
    marked = fmt.mark_flags(frame)
    config = labels.column_config(marked.columns, models)
    if "flag" in marked.columns:
        config["flag"] = st.column_config.Column(help=FLAG_HELP)
    for column, text in (extra_help or {}).items():
        config[column] = st.column_config.Column(help=text)
    st.dataframe(marked, column_config=config, hide_index=True, width="stretch")


def when(value: object) -> str:
    """A time as UTC text, or "unknown"."""
    if not isinstance(value, dt.datetime):
        return "unknown"
    return value.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def header(title: str) -> None:
    """A page's title and the freshness banner (R6.1): when the extract was made, the newest
    mart's modification, and the commit; in season, the stale warning too (R6.2)."""
    st.title(title)
    info = data.query("freshness")
    if info.empty:
        st.error("The extract has no extract_info row, so its age is unknown.")
        st.stop()
    row = info.iloc[0]
    extracted_at = row["extracted_at"].to_pydatetime()
    modified = row["warehouse_modified_at"]
    newest = when(modified.to_pydatetime()) if pd.notna(modified) else "unknown"
    commit = row["git_commit"] if pd.notna(row["git_commit"]) else "unknown"
    st.caption(f"{BANNER} {when(extracted_at)} · newest mart modified {newest} · commit {commit}")
    if freshness.is_stale(extracted_at, freshness.current_time()):
        st.warning(STALE)
