#!/usr/bin/env bash
# Spec 0156 (after spec 0150, R6.2): the smallest DuckDB memory limit on a ladder under which
# load and `dbt build` pass, from an empty warehouse, for each landing root. The profile is
# the committed one plus memory_limit, and optionally a dbt or a DuckDB thread count.
#
#   OUT=/path/to/scratch ROOTS="raw_2026 raw" RUNGS="1 2 4 8" \
#     [THREADS=<dbt threads>] [DTHREADS=<duckdb threads>] [SUFFIX=_label] \
#     docs/specs/0156-build-memory-flat-across-seasons/probes/ladder.sh
#
# ROOTS name directories under data/ (data/raw_2026 holds 2026 alone). "Pass": the process
# is not killed and no node errors (a test failing by its own assertion is a pass). Run
# from the repository root; nothing is written outside OUT.
set -u
REPO=$(pwd)
OUT=${OUT:?set OUT to a scratch directory}
for root in ${ROOTS:-raw_2026 raw}; do
  for gb in ${RUNGS:-1 2 4 8}; do
    run="$OUT/${root}_${gb}gb${SUFFIX:-}"; mkdir -p "$run/profile"; db="$run/warehouse.duckdb"
    rm -f "$db" "$db.wal"
    # The profile is edited as YAML, not as text: the dev target may already have a
    # `settings:` mapping (ADR 0100), and a second one would silently replace the first.
    uv run python - dbt/profiles.yml "$run/profile/profiles.yml" "$gb" "${THREADS:-}" "${DTHREADS:-}" <<'PY'
import copy, sys
import yaml
src, dst, gb, threads, duckdb_threads = sys.argv[1:]
profile = yaml.safe_load(open(src))
outputs = profile["front_office"]["outputs"]
others = {name: copy.deepcopy(target) for name, target in outputs.items() if name != "dev"}
dev = outputs["dev"]
settings = dev.setdefault("settings", {})
settings["memory_limit"] = f"{gb}GB"
if duckdb_threads:
    settings["threads"] = int(duckdb_threads)
if threads:
    dev["threads"] = int(threads)
yaml.safe_dump(profile, open(dst, "w"), sort_keys=False)
check = yaml.safe_load(open(dst))["front_office"]["outputs"]
assert check["dev"]["settings"]["memory_limit"] == f"{gb}GB", check["dev"]
assert not duckdb_threads or check["dev"]["settings"]["threads"] == int(duckdb_threads)
assert not threads or check["dev"]["threads"] == int(threads)
assert {name: check[name] for name in others} == others, "only the dev target may change"
PY
    uv run python - "$root" "$db" "$gb" > "$run/load.log" 2>&1 <<'PY'
import resource, sys, time
from pathlib import Path
import duckdb
from front_office.landing import LandingZone
from front_office.load import load_landing_zone
root, db, gb = sys.argv[1:]
con = duckdb.connect()
con.execute(f"set memory_limit = '{gb}GB'")
con.execute(f"attach '{db}' as w"); con.execute("use w")
started = time.monotonic()
n = load_landing_zone(con, LandingZone(Path("data") / root))
print(f"load {root} {gb}GB: {n} captures, {time.monotonic() - started:.1f} s, "
      f"peak {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576:.2f} GB")
PY
    load_status=$?
    ( cd dbt && FO_LANDING_ROOT="$REPO/data/$root" FO_DUCKDB_PATH="$db" DBT_PROFILES_DIR="$run/profile" \
        /usr/bin/time -f "build exit %x, %e s, peak %M KB" uv run dbt build \
        --target-path "$run/target" --log-path "$run/logs" > "$run/build.log" 2>&1 )
    verdict=$(python3 - "$run/target/run_results.json" "$run/build.log" <<'PY'
import json, sys
log = open(sys.argv[2]).read()
killed = "exit 137" in log or "exit 9" in log
try:
    results = json.load(open(sys.argv[1]))["results"]
except Exception:
    results = []
errors = [r["unique_id"].split(".")[-1] for r in results if r["status"] == "error"]
fails = sorted(r["unique_id"].split(".")[2] for r in results if r["status"] == "fail")
ok = not killed and not errors and len(results) > 600
print(("PASS" if ok else "FAIL") + f" results={len(results)} errors={len(errors)} "
      f"{errors[:6]} fails={fails} killed={killed}")
PY
)
    echo "$root ${gb}GB${SUFFIX:-} load_exit=$load_status $(tail -1 "$run/load.log") | $(grep 'build exit' "$run/build.log") | $verdict"
    case "$verdict" in PASS*) break ;; esac
  done
done
