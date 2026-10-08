"""Prove that each league-season's models are what they would be if it were built alone.

Spec 0028 R5.3, ADR 0013. Loads fixtures/landing_multi/ into one warehouse and builds it;
then, for each of the four league-seasons, builds that league-season ALONE (its ESPN
folders, plus the season-level ESPN captures such as the pro schedule, its season's MLB
folders, the id map) into a warehouse of its own; then compares
every model. Any model whose rows for a league-season differ between the combined build and
the single build is named. Exit 1 if any differ or any dbt step failed.

Usage:  uv run python scripts/check_tenant_isolation.py [--keep DIR]

--keep DIR keeps the working directory (warehouses, landing copies, dbt logs) for inspection.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import duckdb

from front_office.landing import LandingZone
from front_office.load import connect, load_landing_zone
from warehouse_diff import (
    attach,
    columns,
    compare_relation,
    count_rows,
    list_relations,
    rows_missing_from,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DBT_DIR = REPO_ROOT / "dbt"
MULTI_ROOT = REPO_ROOT / "fixtures/landing_multi"

# dim_players is defined over everything loaded (ADR 0012), so its rows legitimately differ
# between a combined and a single build. It is held to its own dbt tests instead
# (R4.9), which this script runs in every single build and the combined build runs too.
EXEMPT_FROM_ROW_COMPARISON = frozenset({"dim_players"})

LEAGUE_SEASONS = [
    ("111111", 2026),
    ("222222", 2026),
    ("111111", 2027),
    ("222222", 2027),
    ("111111", 2025),
]
# The same var in every build, or the combined and single warehouses would differ by design.
DBT_VARS = ["--target", "ci", "--vars", "{anonymize: true}"]
OWN_TESTS = ["--select", "dim_players", "dim_player_league_seasons"]


class Run:
    """Runs dbt and records seconds and failures."""

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.failures: list[str] = []
        self.started = time.monotonic()
        self.count = 0

    def dbt(self, label: str, args: list[str], db: Path) -> None:
        env = {**os.environ, "DBT_PROFILES_DIR": ".", "FO_CI_DUCKDB_PATH": str(db)}
        self.count += 1
        log = self.workdir / f"dbt_{self.count:02d}_{label}.log"
        t0 = time.monotonic()
        result = subprocess.run(
            ["uv", "run", "dbt", *args],
            cwd=DBT_DIR,
            env=env,
            capture_output=True,
            text=True,
        )
        seconds = time.monotonic() - t0
        log.write_text(result.stdout + result.stderr)
        status = "ok" if result.returncode == 0 else "FAILED"
        print(f"dbt {label}: {status} in {seconds:.1f}s (log: {log})", flush=True)
        if result.returncode != 0:
            self.failures.append(label)
            tail = (result.stdout + result.stderr).splitlines()[-40:]
            print("\n".join("    " + line for line in tail), flush=True)


def load(root: Path, db: Path) -> int:
    con = connect(db)
    try:
        return load_landing_zone(con, LandingZone(root))
    finally:
        con.close()


def copy_single(league: str, season: int, target: Path) -> None:
    """One league-season's ESPN folders, its season's MLB folders, and the id map.

    An ESPN endpoint whose season partition has no `league_id=` level (the pro schedule
    belongs to a season, not a league) is copied whole for that season.
    """
    for source in sorted(MULTI_ROOT.iterdir()):
        for endpoint in sorted(source.iterdir()):
            if source.name == "idmap":
                shutil.copytree(endpoint, target / source.name / endpoint.name)
                continue
            for partition in sorted(endpoint.iterdir()):
                if partition.name != f"season={season}":
                    continue
                season_level = source.name == "espn" and not any(
                    child.name.startswith("league_id=") for child in partition.iterdir()
                )
                if source.name == "espn" and not season_level:
                    shutil.copytree(
                        partition / f"league_id={league}",
                        target / "espn" / endpoint.name / partition.name / f"league_id={league}",
                    )
                else:
                    shutil.copytree(
                        partition, target / source.name / endpoint.name / partition.name
                    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=Path, default=None, metavar="DIR")
    args = parser.parse_args(argv)

    if args.keep:
        # Never clear a directory the caller named: it may hold something else. The
        # workspace must be new or empty.
        if args.keep.exists() and (not args.keep.is_dir() or any(args.keep.iterdir())):
            parser.error(f"--keep {args.keep} exists and is not an empty directory; name a new one")
        args.keep.mkdir(parents=True, exist_ok=True)
        workdir = args.keep.resolve()
    else:
        workdir = Path(tempfile.mkdtemp(prefix="isolation_"))
    try:
        return check(workdir)
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)


def check(workdir: Path) -> int:
    run = Run(workdir)
    if not (DBT_DIR / "dbt_packages").exists():
        run.dbt("deps", ["deps"], workdir / "unused.duckdb")

    combined = workdir / "combined.duckdb"
    print(f"combined: loaded {load(MULTI_ROOT, combined)} captures")
    run.dbt("combined_build", ["build", *DBT_VARS], combined)

    singles: dict[tuple[str, int], Path] = {}
    for league, season in LEAGUE_SEASONS:
        stem = f"single_{league}_{season}"
        root = workdir / f"landing_{stem}"
        copy_single(league, season, root)
        db = workdir / f"{stem}.duckdb"
        print(f"{stem}: loaded {load(root, db)} captures")
        # Seeds first: `dbt run` builds models only, and the models read two seeds.
        run.dbt(f"{stem}_seed", ["seed", *DBT_VARS], db)
        run.dbt(f"{stem}_run", ["run", *DBT_VARS], db)
        run.dbt(f"{stem}_test", ["test", *DBT_VARS, *OWN_TESTS], db)
        singles[(league, season)] = db

    differing = compare(combined, singles)
    total = time.monotonic() - run.started
    print(f"isolation: {differing} differing relation/league-season pairs")
    if run.failures:
        print(f"dbt steps failed: {', '.join(run.failures)}")
    print(f"total wall-clock: {total:.1f}s over {run.count} dbt invocations")
    return 1 if differing or run.failures else 0


def compare(combined: Path, singles: dict[tuple[str, int], Path]) -> int:
    con = duckdb.connect()
    comb = attach(con, combined)
    cat = {key: attach(con, path) for key, path in singles.items()}
    names = {comb: list_relations(con, comb)} | {c: list_relations(con, c) for c in cat.values()}
    differing = 0

    union = set().union(*names.values())
    for catalog, present in names.items():
        for relation in sorted(union - present):
            print(f"MISSING {relation} from {catalog}")
            differing += 1

    for relation in sorted(set.intersection(*names.values())):
        if relation.split(".")[1] in EXEMPT_FROM_ROW_COMPARISON:
            continue
        comb_cols = columns(con, comb, relation)
        has_league, has_season = "league_id" in comb_cols, "season" in comb_cols
        # A season column without a league_id is an MLB model (R4.5: they describe no
        # league but do have seasons); it is checked one way, like the league-free ones.
        # A league_id without a season cannot be sliced to a league-season: malformed.
        if has_league and not has_season:
            print(f"DIFFERS {relation}: has league_id but no season")
            differing += 1
            continue
        for (league, season), single in cat.items():
            if has_league:
                where = (
                    f"cast(league_id as varchar) = '{league}' "
                    f"and cast(season as varchar) = '{season}'"
                )
                diff = compare_relation(con, comb, single, relation, left_where=where)
                bad = diff.differs or diff.left_only_columns or diff.right_only_columns
                detail = (
                    f"combined rows {diff.left_rows}, single rows {diff.right_rows}; "
                    f"only in combined {diff.only_left}, only in single {diff.only_right}"
                    f"; columns only in combined {diff.left_only_columns}, "
                    f"only in single {diff.right_only_columns}"
                )
            else:
                missing = rows_missing_from(con, single, comb, relation)
                bad = missing > 0 or columns(con, single, relation).keys() != comb_cols.keys()
                detail = (
                    f"single rows {count_rows(con, single, relation)}, "
                    f"combined rows {count_rows(con, comb, relation)}; "
                    f"rows of single missing from combined {missing}"
                )
            if bad:
                differing += 1
                print(f"DIFFERS {relation} [{league}, {season}]: {detail}")
    return differing


if __name__ == "__main__":
    sys.exit(main())
