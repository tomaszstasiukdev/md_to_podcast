"""
Extract sections from Markdown (## headers) for batch script generation.
Preserves order and allows content coverage control.
"""

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Section:
    """Section of material: title (from ##) and raw content up to the next ##."""

    title: str
    content: str
    index: int  # order in document


def extract_sections_from_body(body: str) -> list[Section]:
    """
    Split markdown body into sections by ## headers (not ###).
    Text before the first ## is treated as the first section (empty or "Wprowadzenie" title).
    """
    if not (body or "").strip():
        return []

    # Split keeping header: (## Title, content until next ##)
    pattern = r"^##\s+(.+)$"
    parts = re.split(pattern, body.strip(), flags=re.MULTILINE)
    sections: list[Section] = []

    # parts[0] = text before first ## (may be empty or intro)
    # parts[1], parts[2] = first title, first content; parts[3], parts[4] = second ...
    if len(parts) == 1:
        # No ## in document – single section
        content = parts[0].strip()
        if content:
            sections.append(Section(title="", content=content, index=0))
        return sections

    # At least one ##
    intro = parts[0].strip()
    if intro:
        sections.append(Section(title="Wprowadzenie", content=intro, index=0))

    idx = len(sections)
    for i in range(1, len(parts) - 1, 2):
        title = parts[i].strip()
        content = (parts[i + 1] if i + 1 < len(parts) else "").strip()
        if not title and not content:
            continue
        sections.append(Section(title=title, content=content, index=idx))
        idx += 1

    # Last section with title but no content (odd number of parts after intro)
    if len(parts) >= 2 and len(parts) % 2 == 0:
        last_title = parts[-1].strip()
        if last_title:
            sections.append(Section(title=last_title, content="", index=idx))

    return sections


# Sections to skip or treat minimally (course meta, tasks, links) – Polish titles from source MD
SECTION_TITLES_TO_MINIMIZE = frozenset({
    "fabuła",
    "transkrypcja filmu z fabułą",
    "jak działają zadania w kursie",
    "zadanie",
    "co należy zrobić",
    "wskazówki",
    "linki do filmu",
})


def should_minimize_section(title: str) -> bool:
    """Whether to treat the section as secondary (short mention or skip)."""
    t = (title or "").strip().lower()
    return any(t.startswith(k) or k in t for k in SECTION_TITLES_TO_MINIMIZE)
