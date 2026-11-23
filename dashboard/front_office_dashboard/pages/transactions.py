"""Transactions: the season's adds and drops, with what each player did afterwards."""

import streamlit as st

from front_office_dashboard import common, data
from front_office_dashboard import format as fmt

common.header("Transactions")
platform, league_id, season = common.league_season("transactions")
transactions = data.query("transactions", platform=platform, league_id=league_id, season=season)

if transactions.empty:
    st.info("No transactions for this league-season.")
else:
    st.caption("Innings are shown from outs_recorded, in whole innings and thirds (6.1 = 6 1/3).")
    common.show(
        fmt.with_innings(transactions),
        ["fct_transaction_impact", "dim_fantasy_teams", "dim_player_league_seasons"],
        {"innings": "Innings pitched from outs_recorded: 6.1 is six and a third. Display only."},
    )
