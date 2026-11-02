"""M4: on BigQuery, does a JavaScript fold over an ordered array give DuckDB's digits?
Literals only: no table is read. Run with: uv run --group bigquery python m4_bq_fold.py <project>"""

import sys

from google.cloud import bigquery

client = bigquery.Client(project=sys.argv[1])
sql = r"""
create temp function fold_sum(xs array<float64>) returns float64 language js as r'''
  if (xs.length == 0) return null; let s = 0; for (const x of xs) s += x; return s;''';
create temp function fold_corr(ps array<struct<y float64, x float64>>) returns float64
language js as r'''
  let n = 0, mx = 0, my = 0, co = 0, cx = 0, sx = 0, ax = 0, cy = 0, sy = 0, ay = 0;
  for (const p of ps) {
    if (p.y === null || p.x === null) continue;
    n += 1; const dx = p.x - mx; mx += dx / n; my += (p.y - my) / n; co += dx * (p.y - my);
    cx += 1; let d = p.x - sx; sx = sx + d / cx; ax += d * (p.x - sx);
    cy += 1; d = p.y - sy; sy = sy + d / cy; ay += d * (p.y - sy);
  }
  if (n == 0) return null;
  const stx = Math.sqrt(ax / cx), sty = Math.sqrt(ay / cy);
  if (stx == 0 || sty == 0) return null;
  return (co / n) / (stx * sty);''';
with t as (select * from unnest([
  struct(1 as k, 0.1 as v), (2, 0.2), (3, 0.3)])),
d as (select * from unnest([
  struct(3 as m, true as h, 229.83 as v), (3, false, 350.73), (2, true, 108.5),
  (2, false, 128.16), (1, true, 336.62), (1, false, 295.48)])),
c1 as (select * from unnest([struct(1 as p, 2.0 as y, 4.0 as x), (2, 4.0, 8.0), (3, 1.0, 2.0)])),
c2 as (select * from unnest([struct(5 as p, 2.7 as y, 7.5 as x), (4, 2.5, 1.2), (3, 2.7, 1.2),
  (2, 3.9, 2.0), (1, 3.4, 8.9)]))
select
  (select fold_sum(array_agg(v order by k)) from t) = 0.6000000000000001 as sum_eq,
  (select fold_sum(array_agg(v order by k desc)) from t) = 0.6 as sum_desc_eq,
  (select fold_sum(array_agg(v order by m, h)) / count(*) from d) = 241.5533333333333 as avg_eq,
  (select fold_corr(array_agg(struct(y, x) order by p)) from c1) = 1.0000000000000002 as corr1_eq,
  (select fold_corr(array_agg(struct(y, x) order by p)) from c2) = 0.14953126241169692 as corr2_eq,
  (select fold_corr(array_agg(struct(y, x) order by p desc)) from c2)
    = 0.14953126241169695 as corr2_desc_eq,
  (select fold_sum(array_agg(v order by m, h)) / count(*) from d) as avg_value
"""
job = client.query(sql)
for row in job.result():
    print(dict(row))
print("bytes billed:", job.total_bytes_billed)
