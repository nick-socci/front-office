"""Reading SQL text for the dbt text rules (ordered aggregates, ADR 0046; ties, ADR 0108).

Both rules read SQL as text, not parsed and not rendered: they need the code with comments
and string literals blanked, and the same test for a ``--`` comment that claims an exemption
on the line of a call or on the comment lines directly above it. The two rules differ only in
the marker they look for, so the reading lives here once.
"""

import re

NOT_NEWLINE = re.compile(r"[^\n]")


def sql_code(sql: str) -> str:
    """`sql` with comments and string literals blanked, character for character.

    One pass, so whichever opens first wins: a `--` inside a string is part of the string, and
    an apostrophe inside a comment is part of the comment. Newlines are kept, so line numbers
    stay true. A double-quoted span on one line (an identifier, or a string in Jinja) is kept
    as it is, so that an apostrophe inside it does not open a string.
    """
    out: list[str] = []
    at, end = 0, len(sql)

    def blanked(stop: int) -> int:
        out.append(NOT_NEWLINE.sub(" ", sql[at:stop]))
        return stop

    def after(closer: str, start: int) -> int:
        found = sql.find(closer, start)
        return end if found < 0 else found + len(closer)

    while at < end:
        if sql.startswith("{#", at):
            at = blanked(after("#}", at + 2))
        elif sql.startswith("--", at):
            newline = sql.find("\n", at)
            at = blanked(end if newline < 0 else newline)
        elif sql.startswith("/*", at):
            at = blanked(after("*/", at + 2))
        elif sql[at] == "'":
            close = at + 1
            while close < end and (sql[close] != "'" or sql.startswith("''", close)):
                close += 2 if sql[close] == "'" else 1
            at = blanked(min(close + 1, end))
        elif sql[at] == '"' and '"' in sql[at + 1 : after("\n", at + 1)]:
            close = sql.index('"', at + 1)
            out.append(sql[at : close + 1])
            at = close + 1
        else:
            out.append(sql[at])
            at += 1
    return "".join(out)


def line_comment(line: str) -> str | None:
    """The text after the first `--` that is not inside a string literal, or None.

    Quotes are tracked only up to that point: after it the line is prose, and an apostrophe
    in it is not a string.
    """
    quoted = False
    for at, char in enumerate(line):
        if char == "'":
            quoted = not quoted
        elif not quoted and line.startswith("--", at):
            return line[at + 2 :]
    return None


def is_exempt(lines: list[str], number: int, exemption: re.Pattern[str]) -> bool:
    """True when a comment on the call's line (1-based `number`), or the comment lines
    directly above it, matches `exemption`."""

    def claims(line: str) -> bool:
        comment = line_comment(line)
        return comment is not None and bool(exemption.search(comment))

    if claims(lines[number - 1]):
        return True
    above = number - 2
    while above >= 0 and lines[above].lstrip().startswith("--"):
        if claims(lines[above]):
            return True
        above -= 1
    return False
