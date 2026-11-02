"""M1: is DuckDB's ordered sum/avg a plain left-to-right double sum? Read-only."""

import math
import sys
from collections import defaultdict

import duckdb

c = duckdb.connect(sys.argv[1], read_only=True)
rows = c.sql("""
    select league_id, season, category_key, matchup_id, standard_margin * standard_margin as v
    from intermediate.int_fantasy__reported_matchup_margins where is_measured
    order by league_id, season, category_key, matchup_id
""").fetchall()
duck = {
    (a, b, k): (s, m)
    for a, b, k, s, m in c.sql("""
    select league_id, season, category_key,
        sum(standard_margin * standard_margin order by matchup_id),
        avg(standard_margin * standard_margin order by matchup_id)
    from intermediate.int_fantasy__reported_matchup_margins where is_measured
    group by all
""").fetchall()
}
groups = defaultdict(list)
for a, b, k, _, v in rows:
    groups[(a, b, k)].append(v)
eq_seq = eq_fsum = eq_avg = eq_avg_f = 0
for key, vs in groups.items():
    s = 0.0
    for v in vs:
        s += v
    ds, dm = duck[key]
    eq_seq += s == ds
    eq_fsum += math.fsum(vs) == ds
    eq_avg += (s / len(vs)) == dm
    eq_avg_f += (math.fsum(vs) / len(vs)) == dm
n = len(groups)
print(f"groups {n}, terms {len(rows)}")
print(f"sum: equal to left-to-right {eq_seq}/{n}, equal to fsum {eq_fsum}/{n}")
print(f"avg: equal to left-to-right/n {eq_avg}/{n}, equal to fsum/n {eq_avg_f}/{n}")
