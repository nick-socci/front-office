"""Tests for the ESPN seed generator (scripts/make_espn_seeds.py): lineup slots and rate stats.

What they catch:
- `is_injured_list_slot` drifting from "true for exactly IL" (lineup decisions, #12, never
  treat an injured-list slot as a candidate, and BE must stay a usable bench slot);
- the committed seed differing from what the script generates, i.e. a hand-edit or a seed
  nobody regenerated after the script changed;
- `is_rate` flagging other than ESPN's 15 rate stats (ADR 0099): a rate left out is staged
  as a count, a count flagged is dropped from both line models;
- a typo in `RATE_STAT_IDS`, which would name a stat espn-api does not have.

The script is run into a temporary directory; the committed seeds are never written.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

import make_espn_seeds

COMMITTED_SEED = Path(make_espn_seeds.__file__).resolve().parent.parent / "dbt/seeds"


@pytest.fixture
def generated_seeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(make_espn_seeds, "SEED_DIR", tmp_path)
    make_espn_seeds.main()
    return tmp_path


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_only_the_injured_list_slot_is_flagged(generated_seeds: Path) -> None:
    rows = read_rows(generated_seeds / "espn_lineup_slots.csv")
    flagged = {row["slot_abbrev"] for row in rows if row["is_injured_list_slot"] == "True"}
    unflagged = {row["slot_abbrev"] for row in rows if row["is_injured_list_slot"] == "False"}
    assert flagged == {"IL"}
    assert {"BE", "C", "UTIL", "SP"} <= unflagged
    assert len(flagged) + len(unflagged) == len(rows)


def test_injured_list_flag_is_the_last_column(generated_seeds: Path) -> None:
    header = (generated_seeds / "espn_lineup_slots.csv").read_text().splitlines()[0]
    assert header.split(",")[-2:] == ["slot_role", "is_injured_list_slot"]


def test_committed_lineup_slots_seed_is_what_the_script_generates(generated_seeds: Path) -> None:
    generated = (generated_seeds / "espn_lineup_slots.csv").read_text()
    committed = (COMMITTED_SEED / "espn_lineup_slots.csv").read_text()
    assert committed == generated


EXPECTED_RATE_STAT_IDS = {2, 9, 17, 18, 19, 29, 38, 41, 43, 47, 49, 55, 59, 71, 82}


def test_stat_ids_seed_ends_with_the_is_rate_column(generated_seeds: Path) -> None:
    header = (generated_seeds / "espn_stat_ids.csv").read_text().splitlines()[0]
    assert header.split(",") == ["stat_id", "stat_abbrev", "display_label", "is_rate"]


def test_exactly_the_rate_stats_are_flagged(generated_seeds: Path) -> None:
    rows = read_rows(generated_seeds / "espn_stat_ids.csv")
    assert {row["is_rate"] for row in rows} == {"true", "false"}
    flagged = {int(row["stat_id"]) for row in rows if row["is_rate"] == "true"}
    assert flagged == EXPECTED_RATE_STAT_IDS


def test_committed_stat_ids_seed_is_what_the_script_generates(generated_seeds: Path) -> None:
    generated = (generated_seeds / "espn_stat_ids.csv").read_text()
    committed = (COMMITTED_SEED / "espn_stat_ids.csv").read_text()
    assert committed == generated


def test_a_rate_id_espn_api_does_not_know_stops_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(make_espn_seeds, "SEED_DIR", tmp_path)
    monkeypatch.setattr(make_espn_seeds, "RATE_STAT_IDS", frozenset({2, 99999}))
    with pytest.raises(SystemExit, match="99999"):
        make_espn_seeds.main()
    assert list(tmp_path.iterdir()) == []
