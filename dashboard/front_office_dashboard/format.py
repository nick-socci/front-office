"""Display-only formatting (spec 0232 R3.3, R3.4).

Nothing here is read back: a formatted value is text for a page, and every number a page
computes with stays the mart's column (rule 4).
"""

from __future__ import annotations

import pandas as pd

FLAG_COLUMNS = ("has_unverified_inputs", "is_unvalued")
MARK = "⚠"


def innings(outs: float | None) -> str:
    """Innings pitched as whole innings and thirds from `outs_recorded`: 19 outs is "6.1"
    (six and a third), 20 is "6.2", 21 is "7.0". "" for a missing count. For display only: the
    text is never a number to add."""
    if outs is None or pd.isna(outs):
        return ""
    whole, thirds = divmod(int(outs), 3)
    return f"{whole}.{thirds}"


def with_innings(frame: pd.DataFrame) -> pd.DataFrame:
    """A copy with an `innings` text column beside `outs_recorded`, which stays as it is."""
    shown = frame.copy()
    shown.insert(
        list(shown.columns).index("outs_recorded") + 1,
        "innings",
        [innings(outs) for outs in shown["outs_recorded"]],
    )
    return shown


def mark_flags(frame: pd.DataFrame) -> pd.DataFrame:
    """A copy with a leading `flag` column holding "⚠" on each row where `has_unverified_inputs`
    or `is_unvalued` is true (R3.4). A frame with neither column comes back as it is."""
    present = [c for c in FLAG_COLUMNS if c in frame.columns]
    if not present:
        return frame
    flagged = pd.Series(False, index=frame.index)
    for column in present:
        flagged = flagged | frame[column].fillna(False).astype(bool)
    marked = frame.copy()
    marked.insert(0, "flag", [MARK if on else "" for on in flagged])
    return marked
