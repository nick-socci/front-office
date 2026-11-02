"""M2: can DuckDB's ordered corr be reproduced by a left-to-right port? Read-only."""

import math
import sys
from collections import defaultdict

import duckdb


def duck_corr(pairs):
    # corr(y, x): covar_pop(y, x) / (stddev_pop(y) * stddev_pop(x)), each streamed (Welford).
    n = 0
    mx = my = co = 0.0
    sx = [0, 0.0, 0.0]
    sy = [0, 0.0, 0.0]

    def wel(s, v):
        s[0] += 1
        d = v - s[1]
        s[1] = s[1] + d / s[0]
        s[2] += d * (v - s[1])

    for y, x in pairs:
        if y is None or x is None:
            continue
        n += 1
        dx = x - mx
        mx += dx / n
        my += (y - my) / n
        co += dx * (y - my)
        wel(sx, x)
        wel(sy, y)
    if n == 0:
        return None
    cov = co / n
    stx = math.sqrt(sx[2] / sx[0])
    sty = math.sqrt(sy[2] / sy[0])
    if stx == 0 or sty == 0:
        return None
    return cov / (stx * sty)


c = duckdb.connect(sys.argv[1], read_only=True)
base = """from marts.fct_player_season_value where total_value is not null"""
rows = c.sql(f"""select league_id, season, fantasy_team_id, platform_player_id,
    total_value, total_value * 1.7 + sin(platform_player_id) as other {base}
    order by all""").fetchall()
duck = {
    (a, b, t): r
    for a, b, t, r in c.sql(f"""select league_id, season, fantasy_team_id,
    corr(total_value * 1.7 + sin(platform_player_id), total_value
        order by platform_player_id) {base} group by all""").fetchall()
}
g = defaultdict(list)
for a, b, t, _, x, y in rows:
    g[(a, b, t)].append((y, x))
eq = sum(duck_corr(v) == duck[k] for k, v in g.items())
print(f"groups {len(g)}: port equal to DuckDB's ordered corr in {eq}")
# The two unit tests' inputs, in player order.
print(
    duck_corr([(2, 4), (4, 8), (1, 2)]),
    duck_corr([(3.4, 8.9), (3.9, 2.0), (2.7, 1.2), (2.5, 1.2), (2.7, 7.5)]),
)
