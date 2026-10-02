"""CHANGELOG.md (bundled with the app): what changed in each release.

Sections are "## <version> (<date>)" or "## Unreleased". The What's new
view shows the whole file; the release workflow publishes one section as
the GitHub release notes:

    python -m app.changelog 0.1.1 > notes.md

No other app imports, so CI can run it without the app's requirements.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Next to the package, or in PyInstaller's unpack dir (as in app.config).
CHANGELOG_FILE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "CHANGELOG.md"
_HEADING = re.compile(r"^## +(\S+)(?: +\((\d{4}-\d{2}-\d{2})\))?\s*$")


@dataclass(frozen=True)
class Section:
    version: str          # "0.1.0", "0.1.0-beta.6" or "Unreleased"
    date: str             # "" for Unreleased
    body: str             # Markdown, without the heading


def read_text() -> str:
    try:
        return CHANGELOG_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def sections(text: str | None = None) -> list[Section]:
    out: list[Section] = []
    version = date = None
    lines: list[str] = []
    for line in (read_text() if text is None else text).splitlines():
        match = _HEADING.match(line)
        if match:
            if version is not None:
                out.append(Section(version, date or "", "\n".join(lines).strip()))
            version, date, lines = match.group(1), match.group(2), []
        elif version is not None:
            lines.append(line)
    if version is not None:
        out.append(Section(version, date or "", "\n".join(lines).strip()))
    return out


def section(version: str, text: str | None = None) -> Section | None:
    version = version.removeprefix("v")
    return next((s for s in sections(text) if s.version == version), None)


def display_markdown(text: str | None = None) -> str:
    """The file without its title and intro, for the What's new view."""
    text = read_text() if text is None else text
    start = text.find("\n## ")
    return text[start + 1:] if start >= 0 else text


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")      # Windows consoles default to cp1252 ("→" etc.)
    found = section(sys.argv[1]) if len(sys.argv) == 2 else None
    if found is None or not found.body:
        sys.exit(f"CHANGELOG.md has no section for {sys.argv[1:]}")
    print(found.body)
