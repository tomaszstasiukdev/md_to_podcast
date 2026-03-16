"""
Load Markdown files from a folder: path, name, raw content, frontmatter, body.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ENCODING = "utf-8"


@dataclass
class MarkdownDocument:
    """A single Markdown document with metadata."""

    path: Path
    filename: str
    raw_content: str
    frontmatter: dict
    body: str


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """
    Parse optional YAML frontmatter between the first two '---'.
    Returns (metadata dict, body without frontmatter).
    """
    frontmatter: dict = {}
    body = content
    if content.strip().startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            import yaml

            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
                if not isinstance(frontmatter, dict):
                    frontmatter = {}
            except Exception as e:
                logger.warning("Failed to parse frontmatter YAML: %s", e)
            body = parts[2].lstrip("\n")
    return frontmatter, body


def load_markdown_file(path: Path) -> MarkdownDocument | None:
    """
    Load one .md file as UTF-8. Returns MarkdownDocument or None on error.
    """
    try:
        raw = path.read_text(encoding=ENCODING)
    except Exception as e:
        logger.error("Cannot read file %s: %s", path, e)
        return None
    frontmatter, body = _parse_frontmatter(raw)
    return MarkdownDocument(
        path=path,
        filename=path.name,
        raw_content=raw,
        frontmatter=frontmatter,
        body=body,
    )


def find_and_load_markdown_files(
    input_dir: Path,
    pattern: str = "*.md",
) -> list[MarkdownDocument]:
    """
    Find all .md files in input_dir matching pattern and load them.
    Returns list of documents sorted alphabetically by filename.
    """
    if not input_dir.is_dir():
        logger.warning("Input directory does not exist: %s", input_dir)
        return []
    files = sorted(input_dir.glob(pattern))
    documents: list[MarkdownDocument] = []
    for f in files:
        if not f.is_file():
            continue
        doc = load_markdown_file(f)
        if doc:
            documents.append(doc)
    return documents
