"""Players: the season's players by total_value, and one player's category values, facts and
value in each season he was started."""

import pandas as pd
import streamlit as st

from front_office_dashboard import common, data

ALL = "All"

common.header("Players")
platform, league_id, season = common.league_season("players")
where = {"platform": platform, "league_id": league_id, "season": season}
players = data.query("players", **where)

if players.empty:
    st.info("No players for this league-season.")
else:
    left, right = st.columns(2)
    teams = sorted(players["team_name"].dropna().unique())
    team = left.selectbox("Fantasy team", [ALL, *teams], key="players_team")
    groups = sorted(players["replacement_group"].dropna().unique())
    group = right.selectbox("Replacement group", [ALL, *groups], key="players_group")
    if team != ALL:
        players = players[players["team_name"] == team]
    if group != ALL:
        players = players[players["replacement_group"] == group]
    players = players.reset_index(drop=True)
    common.show(players, ["fct_player_season_value", "dim_player_league_seasons"])

    rows = players.to_dict("records")
    if rows:

        def label(i: int) -> str:
            row = rows[i]
            name = row["player_name"] if pd.notna(row["player_name"]) else "unnamed"
            return f"{name} ({row['team_name']})"

        chosen = st.selectbox("Player", range(len(rows)), format_func=label, key="players_player")
        row = rows[chosen]
        platform_player_id = int(common.plain(row["platform_player_id"]))
        st.subheader(f"{label(chosen)}: category values")
        categories = data.query("player_categories", **where, platform_player_id=platform_player_id)
        common.show(categories, ["fct_player_category_value", "dim_fantasy_teams"])
        if pd.notna(row["mlbam_player_id"]):
            mlbam_player_id = int(common.plain(row["mlbam_player_id"]))
            st.subheader("Facts")
            common.show(
                data.query("player_facts", mlbam_player_id=mlbam_player_id), ["dim_players"]
            )
            st.subheader("Total value in each season started")
            common.show(
                data.query("player_seasons", mlbam_player_id=mlbam_player_id),
                ["fct_player_season_value", "dim_fantasy_teams"],
            )
        else:
            st.caption("This player has no MLB id, so no MLB facts or other seasons.")
