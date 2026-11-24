"""Lineups: a team's lineup decisions by day, and its category results per matchup, actual
against optimal."""

import streamlit as st

from front_office_dashboard import common, data

common.header("Lineups")
platform, league_id, season = common.league_season("lineups")
where = {"platform": platform, "league_id": league_id, "season": season}
teams = data.query("teams", **where).to_dict("records")

if not teams:
    st.info("No teams for this league-season.")
else:
    chosen = st.selectbox(
        "Team",
        range(len(teams)),
        format_func=lambda i: str(teams[i]["team_name"]),
        key="lineups_team",
    )
    team = {**where, "fantasy_team_id": int(common.plain(teams[chosen]["fantasy_team_id"]))}
    st.subheader("By day")
    common.show(data.query("lineup_decisions", **team), ["fct_lineup_decisions"])
    st.subheader("By matchup and category")
    common.show(
        data.query("lineup_categories", **team),
        ["fct_lineup_decision_categories", "dim_fantasy_teams"],
    )
