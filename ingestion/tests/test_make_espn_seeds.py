"""Tests for the ESPN seed generator (scripts/make_espn_seeds.py), lineup slots only.

What they catch:
- `is_injured_list_slot` drifting from "true for exactly IL" (lineup decisions, #12, never
  treat an injured-list slot as a candidate, and BE must stay a usable bench slot);
- the committed seed differing from what the script generates, i.e. a hand-edit or a seed
  nobody regenerated after the script changed.

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
