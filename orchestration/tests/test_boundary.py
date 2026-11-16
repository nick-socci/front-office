"""R1.1: the orchestration reaches `front_office` through the CLI and two modules only.

Catches: an import that bypasses the CLI boundary (a fetch, a loader or a parser called from
Dagster, so the pipeline is described twice); a code location that does not load from the
repository root (the wheel's packages, the manifest parse, the settings defaults).
"""

import ast
import os
import subprocess
from pathlib import Path

from front_office_pipeline import settings

ORCHESTRATION = settings.REPO_ROOT / "orchestration"
ALLOWED = {
    "season.py": {"front_office.landing"},
    "cli.py": {"front_office.privacy"},
}


def front_office_imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if a.name.split(".")[0] == "front_office"}
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.split(".")[0] == "front_office"
        ):
            if node.module == "front_office":
                # `from front_office import privacy` names the module it imports.
                found |= {f"front_office.{a.name}" for a in node.names}
            else:
                found.add(node.module)
    return found


def test_only_season_and_cli_import_front_office_and_only_two_modules() -> None:
    files = sorted(
        p
        for p in ORCHESTRATION.rglob("*.py")
        if "tests" not in p.parts and "__pycache__" not in p.parts
    )
    assert files
    for path in files:
        assert front_office_imports(path) <= ALLOWED.get(path.name, set()), path


def test_the_two_allowed_imports_are_used() -> None:
    """Catches the scan passing because it finds nothing."""
    package = ORCHESTRATION / "front_office_pipeline"
    assert front_office_imports(package / "season.py") == {"front_office.landing"}
    assert front_office_imports(package / "cli.py") == {"front_office.privacy"}


def test_dagster_definitions_validate_loads_the_code_location_from_the_root() -> None:
    """Runs `dagster definitions validate` as a person would, with FO_WAREHOUSE unset."""
    env = {k: v for k, v in os.environ.items() if k not in {"FO_WAREHOUSE", "FO_BQ_PROJECT"}}
    completed = subprocess.run(
        ["uv", "run", "dagster", "definitions", "validate", "-m", "front_office_pipeline"],
        cwd=settings.REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
