"""M5: what a JavaScript fold costs on BigQuery at the scale of the largest caller
(int_fantasy__candidate_day_values, about 2e5 groups): 2e5 groups of 12 terms, from
generate_array, so no table is read. Native sum on the same rows for comparison."""

import sys

from google.cloud import bigquery

client = bigquery.Client(project=sys.argv[1])
fn = r"""create temp function fold_sum(xs array<float64>) returns float64 language js as r'''
  if (xs.length == 0) return null; let s = 0; for (const x of xs) s += x; return s;''';"""
rows = (
    """from unnest(generate_array(1, 200000)) as g cross join unnest(generate_array(1, 12)) as k"""
)
for name, agg in [
    ("js fold", "fold_sum(array_agg(sin(g * k) order by k))"),
    ("native sum", "sum(sin(g * k))"),
]:
    cfg = bigquery.QueryJobConfig(use_query_cache=False)
    job = client.query(
        f"{fn if 'fold' in agg else ''} select count(*), sum(s)"
        f" from (select g, {agg} as s {rows} group by g)",
        job_config=cfg,
    )
    job.result()
    print(
        f"{name}: wall {(job.ended - job.started).total_seconds():.1f} s,"
        f" slot {job.slot_millis / 1000:.1f} s, billed {job.total_bytes_billed}"
    )
