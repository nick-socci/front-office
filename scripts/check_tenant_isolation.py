"""Prove that a league-season's models depend only on its own league's captures, up to its season.

Spec 0028 R5.3, ADR 0013 as amended by ADR 0028; spec 0057 R5. The invariant: a
league-season's rows depend only on its own league's captures of that season and of earlier
ones (ADR 0028: the blended category scale reads the league's earlier seasons on purpose).
Another league's captures, or a later season's, changing its rows is what this catches.

Loads fixtures/landing_multi/ into one warehouse and builds it; then, for each league-season,
builds it with its league's earlier seasons into a warehouse of its own: that league's ESPN
folders for the season and every earlier season, the season-level ESPN captures such as the
pro schedule, the MLB folders of those seasons, the id map. Never a later season, never
another league. Then compares every model on the rows of the league-season under test. Any
model whose rows for it differ between the combined build and the single build is named.
Exit 1 if any differ or any dbt step failed.

Every build, combined and single, runs with fantasy_scale_prior_matchups at 2 (spec 0057
R5.2), so the blended category scale is in use wherever a league-season has an earlier
season and the fallback runs where it has none. The main CI build keeps the default.

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
from collections.abc import Iterable
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
# The same vars in every build, or the combined and single warehouses would differ by design.
# The lowered threshold makes two fixture matchups enough to blend in an earlier season.
DBT_VARS = [
    "--target",
    "ci",
    "--vars",
    "{anonymize: true, fantasy_scale_prior_matchups: 2}",
]
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


def seasons_to_copy(season: int, available: Iterable[int]) -> list[int]:
    """The season under test and every earlier one the league has; never a later one."""
    return sorted(s for s in set(available) if s <= season)


def league_seasons(root: Path, league: str) -> list[int]:
    """The seasons for which `root` holds ESPN captures of `league`."""
    found: set[int] = set()
    for league_dir in (root / "espn").glob(f"*/season=*/league_id={league}"):
        found.add(int(league_dir.parent.name.removeprefix("season=")))
    return sorted(found)


def copy_single(league: str, season: int, target: Path) -> None:
    """One league-season's inputs: its league's ESPN folders for the season and every
    earlier season, those seasons' MLB folders, and the id map.

    An ESPN endpoint whose season partition has no `league_id=` level (the pro schedule
    belongs to a season, not a league) is copied whole for each of those seasons.
    """
    seasons = seasons_to_copy(season, league_seasons(MULTI_ROOT, league))
    wanted = {f"season={s}" for s in seasons}
    for source in sorted(MULTI_ROOT.iterdir()):
        for endpoint in sorted(source.iterdir()):
            if source.name == "idmap":
                shutil.copytree(endpoint, target / source.name / endpoint.name)
                continue
            for partition in sorted(endpoint.iterdir()):
                if partition.name not in wanted:
                    continue
                season_level = source.name == "espn" and not any(
                    child.name.startswith("league_id=") for child in partition.iterdir()
                )
                if source.name == "espn" and not season_level:
                    own = partition / f"league_id={league}"
                    if own.is_dir():
                        shutil.copytree(
                            own,
                            target / "espn" / endpoint.name / partition.name / own.name,
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
        # league but do have seasons); it is checked one way, like the league-free ones:
        # every row of the single build, earlier seasons included, is in the combined one.
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
                # The single build now holds the league's earlier seasons too, so its
                # side is sliced to the league-season under test as well. What lies
                # outside the slice must be that league's own earlier seasons and
                # nothing else: another league's row, or a later season's, is a leak.
                outside = (
                    f"coalesce(not (cast(league_id as varchar) = '{league}' "
                    f"and try_cast(season as bigint) <= {season}), true)"
                )
                strays = count_rows(con, single, relation, outside)
                diff = compare_relation(
                    con, comb, single, relation, left_where=where, right_where=where
                )
                bad = (
                    diff.differs or diff.left_only_columns or diff.right_only_columns or strays > 0
                )
                detail = (
                    f"combined rows {diff.left_rows}, single rows {diff.right_rows}; "
                    f"only in combined {diff.only_left}, only in single {diff.only_right}"
                    f"; columns only in combined {diff.left_only_columns}, "
                    f"only in single {diff.right_only_columns}"
                    f"; single rows of another league or a later season {strays}"
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
