"""The dashboard: five pages over one extract of the marts (spec 0232, ADR 0147).

Every page shows the freshness banner (R6.1) and, when the extract is stale in season, a
warning (R6.2): `common.header` does, because AppTest renders a page without this file. With no
extract there is one page saying how to make one, and nothing else (R6.3).

Run from `dashboard/`:  streamlit run front_office_dashboard/app.py
"""

import sys
from pathlib import Path

# Streamlit puts this file's folder on the path, not its parent: the package is the parent's.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from front_office_dashboard import data  # noqa: E402


def no_extract() -> None:
    st.title("No extract yet")
    st.error(f"There is no extract at {data.extract_path()}, so there is nothing to show.")
    st.write("Make one from a built warehouse:")
    st.code(
        "front-office extract-marts --db data/warehouse.duckdb --out data/dashboard/extract.duckdb",
        language="bash",
    )
    st.write(
        "On the host the daily run makes it after the marts build; the runbook has the command "
        "to make one by hand."
    )


st.set_page_config(page_title="Front Office", layout="wide")
if not data.extract_path().exists():
    no_extract()
    st.stop()
navigation = st.navigation(
    [
        st.Page("pages/standings.py", title="Standings", url_path="standings", default=True),
        st.Page("pages/matchups.py", title="Matchups", url_path="matchups"),
        st.Page("pages/players.py", title="Players", url_path="players"),
        st.Page("pages/lineups.py", title="Lineups", url_path="lineups"),
        st.Page("pages/transactions.py", title="Transactions", url_path="transactions"),
    ]
)
navigation.run()
