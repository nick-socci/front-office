"""M3: the exact-decimal option on DuckDB. Read-only.
(a) is DuckDB's cast of a double to decimal(38, s) the exact rounding of its binary value?
(b) how many of the 138 sums of M1 would change their double result?"""

import sys
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

import duckdb

c = duckdb.connect(sys.argv[1], read_only=True)
for s in (9, 18):
    q = Decimal(1).scaleb(-s)
    rows = c.sql(f"""select v, cast(cast(v as decimal(38, {s})) as varchar) from (
        select distinct standard_margin * standard_margin as v
        from intermediate.int_fantasy__reported_matchup_margins where is_measured)""").fetchall()
    he = sum(Decimal(d) == Decimal(v).quantize(q, ROUND_HALF_EVEN) for v, d in rows)
    hu = sum(Decimal(d) == Decimal(v).quantize(q, ROUND_HALF_UP) for v, d in rows)
    print(f"scale {s}: {len(rows)} distinct values; cast equals exact half-even {he}, half-up {hu}")
    changed = c.sql(f"""select count(*), count(case when a != b then 1 end) from (
        select league_id, season, category_key,
            sum(standard_margin * standard_margin order by matchup_id) as a,
            cast(sum(cast(standard_margin * standard_margin as decimal(38, {s}))) as double) as b
        from intermediate.int_fantasy__reported_matchup_margins
        where is_measured group by all)""").fetchone()
    print(f"  sums: {changed[0]}, double result changed by the decimal route: {changed[1]}")
