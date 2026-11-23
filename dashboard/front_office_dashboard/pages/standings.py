"""Standings: each team's computed record beside ESPN's, in the order ADR 0148 sets."""

import streamlit as st

from front_office_dashboard import common, data

COMPUTED = ("wins", "losses", "ties")
REPORTED = ("reported_wins", "reported_losses", "reported_ties")

common.header("Standings")
platform, league_id, season = common.league_season("standings")
standings = data.query("standings", platform=platform, league_id=league_id, season=season)

if standings.empty:
    st.info("No standings for this league-season.")
else:
    if bool(standings["is_regular_season_complete"].all()):
        st.caption("Ordered by ESPN's playoff seed: the regular season is complete.")
    else:
        st.caption(
            "Ordered by record so far (computed wins, then losses). The playoff seed is ESPN's, "
            "as reported."
        )
    # A computed record that is not ESPN's is marked (null where the league is not head to head).
    differs = standings["wins"].notna() & (
        (standings["wins"] != standings["reported_wins"])
        | (standings["losses"] != standings["reported_losses"])
        | (standings["ties"] != standings["reported_ties"])
    )
    standings.insert(0, "flag", ["⚠" if d else "" for d in differs])
    st.caption("⚠ marks a computed record that differs from the one ESPN reports.")
    common.show(
        standings.drop(columns=["fantasy_team_id"]),
        ["fct_team_standings", "dim_fantasy_teams"],
        {"flag": "The computed record differs from ESPN's reported record."},
    )
