"""Matchups: each matchup of a period, and one matchup's category scores per side."""

import streamlit as st

from front_office_dashboard import common, data

common.header("Matchups")
platform, league_id, season = common.league_season("matchups")
where = {"platform": platform, "league_id": league_id, "season": season}
periods = data.query("matchup_periods", **where)["matchup_period"].tolist()

if not periods:
    st.info("No matchups for this league-season.")
else:
    period = int(st.selectbox("Matchup period", periods, key="matchups_period"))
    matchups = data.query("matchups", **where, matchup_period=period)
    common.show(matchups, ["fct_matchup_results"])
    rows = matchups.to_dict("records")
    if rows:
        chosen = st.selectbox(
            "Matchup",
            range(len(rows)),
            format_func=lambda i: f"{rows[i]['home_team_name']} vs {rows[i]['away_team_name']}",
            key="matchups_matchup",
        )
        matchup_id = int(common.plain(rows[chosen]["matchup_id"]))
        st.subheader("Category scores")
        scores = data.query("matchup_categories", **where, matchup_id=matchup_id)
        common.show(scores, ["fct_matchup_category_scores", "dim_fantasy_teams"])
