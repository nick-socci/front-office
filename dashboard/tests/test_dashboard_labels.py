"""Column descriptions as tooltips (spec 0232 R3.2)."""

from pathlib import Path

from front_office_dashboard import labels

YAML = """
version: 2
models:
  - name: a
    columns:
      - name: wins
        description: >
          Games won,
          as counted.
      - name: season
        data_tests: [not_null]
  - name: b
    columns:
      - name: wins
        description: B's wins.
      - name: only_b
        description: Only in b.
"""


def test_descriptions_are_read_per_model(tmp_path: Path) -> None:
    """Catches a description lost, or a column without one given a made-up text."""
    path = tmp_path / "m.yml"
    path.write_text(YAML)
    found = labels.descriptions(path)
    assert found["a"]["wins"] == "Games won, as counted."
    assert "season" not in found["a"]
    assert found["b"]["only_b"] == "Only in b."


def test_the_first_model_naming_a_column_gives_its_help(tmp_path: Path) -> None:
    """Catches a joined column taking another model's description."""
    path = tmp_path / "m.yml"
    path.write_text(YAML)
    found = labels.descriptions(path)
    config = labels.column_config(["wins", "only_b", "season", "x"], ["b", "a"], found)
    assert set(config) == {"wins", "only_b"}
    assert config["wins"]["help"] == "B's wins."


def test_the_real_descriptions_load() -> None:
    """Catches the YAML moving: the shipped marts file names the standings' record columns."""
    found = labels.descriptions()
    assert "wins" in found["fct_team_standings"]
    assert "mlbam_player_id" in found["fct_player_season_value"]
