"""What counts as a league member's identity, in one place.

This repo is public and ESPN payloads name the people in a private league. The fixture
privacy test and the pre-commit guard (`.agentic/pre-commit-guard`) both import these
patterns, so tightening a rule tightens both.

Scoped to ESPN deliberately: MLB data is public, and MLB's gameGuid is a legitimate GUID
that would trip the pattern.
"""

import re
from collections.abc import Iterator
from typing import Any

# ESPN account ids look like {272E019C-48D5-42F3-B289-C48A1B163E19}.
_HEX = "[0-9A-Fa-f]"
GUID = re.compile(rf"\{{?{_HEX}{{8}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{12}}\}}?")

# Keys whose values identify a person rather than a fantasy team.
FORBIDDEN_KEYS = frozenset(
    {
        "members",
        "owners",
        "primaryOwner",
        "firstName",
        "lastName",
        "displayName",
        # Every transaction message names the ESPN account that made the move.
        "author",
    }
)


def walk(node: Any, path: str = "$") -> Iterator[tuple[str, str, Any]]:
    """Yield (path, key, value) for every key in a nested structure."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield path, key, value
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk(value, f"{path}[{index}]")
