"""Read the header of every ADR file (spec 0133, ADR 0062).

The ADR index used to be a hand-kept table in docs/adr/README.md, which every spec and
build PR edited, so unrelated PRs conflicted there. The index is now generated from the
files themselves. This module reads and checks the header the generator depends on: a
header that would be misread fails here, loudly, rather than publishing a wrong page.

Standard library only: it runs in the docs-site assembler and in the pytest step.
"""

import re
from dataclasses import dataclass
from datetime import date as _date
from fnmatch import fnmatch
from pathlib import Path

STATUS_WORDS = ("proposed", "accepted", "superseded")
LINK_KEYS = ("Status", "Spec", "Amends", "Supersedes")

HEADING = re.compile(r"^# (\d{4})\. (.+)$")
STATUS_WORD = re.compile(r"^([a-z]+)(?=[ ,;]|$)")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
ADR_FILE = "[0-9][0-9][0-9][0-9]-*.md"
ADR_LINK = re.compile(r"\]\(([^)\s#]*?/)?([0-9]{4}-[^)\s#/]*\.md)")


class AdrError(Exception):
    """An ADR file, or the directory of them, that the index cannot be built from."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


@dataclass(frozen=True)
class Adr:
    path: Path
    number: str
    title: str
    status: str
    status_word: str
    date: str
    spec_text: str
    spec_target: str
    amends: str | None
    supersedes: str | None


def _header_lines(text: str) -> list[str]:
    """Everything before the first line starting `## `."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("## "):
            return lines[:i]
    return lines


def _optional(path: Path, header: list[str], key: str) -> str | None:
    """The text of the header's `- <key>: ` line, or None; more than one is an error."""
    prefix = f"- {key}: "
    found = [line[len(prefix) :] for line in header if line.startswith(prefix)]
    if len(found) > 1:
        raise AdrError(path, f"the header has a {key} line more than once")
    return found[0] if found else None


def _required(path: Path, header: list[str], key: str) -> str:
    line = _optional(path, header, key)
    if line is None:
        raise AdrError(path, f"the header has no {key} line")
    return line


def _check_links(path: Path, key: str, line: str) -> None:
    for _text, target in LINK.findall(line):
        if URL_SCHEME.match(target):
            continue
        file_part = target.split("#", 1)[0]
        if file_part and not (path.parent / file_part).exists():
            raise AdrError(path, f"the {key} line links {file_part}, which does not exist")


def read_adr(path: Path) -> Adr:
    header = _header_lines(path.read_text(encoding="utf-8"))
    match = HEADING.match(header[0]) if header else None
    if match is None:
        raise AdrError(path, "the file does not open with a heading `# NNNN. <title>`")
    number, title = match.group(1), match.group(2)
    file_number = path.name[:4]
    if number != file_number:
        raise AdrError(
            path, f"the heading number {number} differs from the filename's {file_number}"
        )

    status = _required(path, header, "Status")
    date = _required(path, header, "Date")
    spec = _required(path, header, "Spec")
    amends = _optional(path, header, "Amends")
    supersedes = _optional(path, header, "Supersedes")

    word_match = STATUS_WORD.match(status)
    status_word = word_match.group(1) if word_match else ""
    if status_word not in STATUS_WORDS:
        raise AdrError(
            path,
            f"the Status line opens with {status_word or status!r}, "
            f"not one of {', '.join(STATUS_WORDS)}",
        )

    if not ISO_DATE.match(date):
        raise AdrError(path, f"the Date {date!r} is not YYYY-MM-DD")
    try:
        _date.fromisoformat(date)
    except ValueError:
        raise AdrError(path, f"the Date {date!r} is not a real date") from None

    spec_links = LINK.findall(spec)
    if len(spec_links) != 1:
        raise AdrError(
            path, f"the Spec line must hold exactly one link, it holds {len(spec_links)}"
        )
    spec_text, spec_target = spec_links[0]

    for key, line in (
        ("Status", status),
        ("Spec", spec),
        ("Amends", amends),
        ("Supersedes", supersedes),
    ):
        if line is not None:
            _check_links(path, key, line)

    return Adr(
        path=path,
        number=number,
        title=title,
        status=status,
        status_word=status_word,
        date=date,
        spec_text=spec_text,
        spec_target=spec_target,
        amends=amends,
        supersedes=supersedes,
    )


def read_all(adr_dir: Path) -> list[Adr]:
    """Every ADR file in `adr_dir`, in number order."""
    if not adr_dir.is_dir():
        raise AdrError(adr_dir, "the ADR directory does not exist")
    files = sorted(adr_dir.glob(ADR_FILE))
    if not files:
        raise AdrError(adr_dir, f"the ADR directory holds no {ADR_FILE} file")
    seen: dict[str, Path] = {}
    for file in files:
        number = file.name[:4]
        if number in seen:
            raise AdrError(
                adr_dir, f"number {number} is used by both {seen[number].name} and {file.name}"
            )
        seen[number] = file
    adrs = [read_adr(file) for file in files]
    _check_amendments(adrs)
    return adrs


def _file_targets(text: str) -> list[str]:
    """The `NNNN-*.md` files, in the same directory, that the links in `text` point to."""
    names = []
    for _text, target in LINK.findall(text):
        file_part = target.split("#", 1)[0]
        if "/" not in file_part and fnmatch(file_part, ADR_FILE):
            names.append(file_part)
    return names


def _named(adr: Adr) -> list[str]:
    """The ADR files an accepted ADR amends or supersedes, by its lines or Status clauses."""
    if adr.status_word != "accepted":
        return []
    names: list[str] = []
    for line in (adr.amends, adr.supersedes):
        if line is not None:
            names.extend(_file_targets(line))
    for clause in adr.status.split(";"):
        clause = clause.lstrip()
        if clause.startswith(("amends", "supersedes")):
            names.extend(_file_targets(clause))
    return names


def _check_amendments(adrs: list[Adr]) -> None:
    """An accepted ADR that amends or supersedes another must be linked from that one's Status."""
    by_name = {adr.path.name: adr for adr in adrs}
    for adr in adrs:
        for name in dict.fromkeys(_named(adr)):
            named = by_name.get(name)
            if named is not None and adr.path.name not in _file_targets(named.status):
                raise AdrError(
                    named.path,
                    f"the Status line does not link {adr.path.name}, which amends or supersedes it",
                )


def readme_links(path: Path) -> list[str]:
    """The `NNNN-*.md` link targets a README holds (it should hold none)."""
    text = path.read_text(encoding="utf-8")
    return [f"{prefix or ''}{name}" for prefix, name in ADR_LINK.findall(text)]
