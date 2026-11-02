"""M6: on BigQuery, do the folds give DuckDB's edge cases (C7)? Literals only: no table is read.

Run with: uv run --group bigquery python m6_bq_edges.py <project>
"""

import sys

from google.cloud import bigquery

client = bigquery.Client(project=sys.argv[1])
sql = r"""
create temp function fold_sum(xs array<float64>) returns float64 language js as r'''
  if (xs === null || xs.length === 0) return null;
  let s = 0; for (const x of xs) s += x; return s;''';
create temp function fold_corr(ps array<struct<y float64, x float64>>) returns float64
language js as r'''
  let n = 0, mx = 0, my = 0, co = 0, sx = 0, ax = 0, sy = 0, ay = 0;
  for (const p of ps || []) {
    if (p.y === null || p.x === null) continue;
    n += 1; const dx = p.x - mx; mx += dx / n; my += (p.y - my) / n; co += dx * (p.y - my);
    let d = p.x - sx; sx = sx + d / n; ax += d * (p.x - sx);
    d = p.y - sy; sy = sy + d / n; ay += d * (p.y - sy);
  }
  if (n === 0) return null;
  return (co / n) / (Math.sqrt(ax / n) * Math.sqrt(ay / n));''';
with only_nulls as (select cast(null as float64) as v, 1 as k union all
               select cast(null as float64), 2),
one_pair as (select 1.0 as y, 2.0 as x, 1 as k),
flat as (select 1.0 as y, 2.0 as x, 1 as k union all select 1.0, 3.0, 2),
null_pairs as (select cast(null as float64) as y, 2.0 as x, 1 as k union all
               select 1.0, cast(null as float64), 2),
neg as (select -0.0 as v, 1 as k),
infs as (select cast('inf' as float64) as v, 1 as k union all
         select cast('-inf' as float64), 2)
select
  (select array_agg(v ignore nulls order by k) is null from only_nulls) as all_null_array_is_null,
  (select fold_sum(array_agg(v ignore nulls order by k)) is null from only_nulls) as sum_null,
  (select fold_sum(array_agg(v ignore nulls order by k)) / nullif(count(v), 0) is null
   from only_nulls) as avg_null,
  (select is_nan(fold_corr(array_agg(struct(y as y, x as x) order by k))) from one_pair)
    as corr_one_pair_nan,
  (select is_nan(fold_corr(array_agg(struct(y as y, x as x) order by k))) from flat)
    as corr_zero_variance_nan,
  (select fold_corr(array_agg(struct(y as y, x as x) order by k)) is null from null_pairs)
    as corr_no_pairs_null,
  (select cast(fold_sum(array_agg(v order by k)) as string) from neg) as sum_negative_zero,
  (select is_nan(fold_sum(array_agg(v order by k))) from infs) as sum_inf_minus_inf_nan
"""
job = client.query(sql)
for row in job.result():
    print(dict(row))
print("bytes billed:", job.total_bytes_billed)
