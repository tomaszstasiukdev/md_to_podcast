"""
STEP 1: Clean and extract content from Markdown.
Removes frontmatter, images, video embeds, redundant links and formatting;
keeps a clear section structure as clean text for model input.
"""

import re
import logging
from pathlib import Path

from .markdown_loader import MarkdownDocument

logger = logging.getLogger(__name__)


def clean_text_fragment(text: str) -> str:
    """
    Clean any markdown fragment (e.g. one section's content).
    Same logic as clean_markdown but for a raw string.
    """
    if not (text or "").strip():
        return ""
    doc = MarkdownDocument(path=Path("."), filename="", raw_content="", frontmatter={}, body=text)
    return clean_markdown(doc)


def clean_markdown(doc: MarkdownDocument) -> str:
    """
    Clean markdown content for LLM input.
    - Images: ![alt](url) -> removed
    - Video embeds (e.g. vimeo, youtube) -> removed or short mention
    - Links [text](url) -> replaced with text only (no URL)
    - Excess formatting (**, __, # headers) -> simplified to plain text
    - Empty sections / multiple newlines -> reduced
    - Code blocks ``` ... ``` -> replaced with placeholder (Polish for podcast)
    - Blockquotes > -> kept as plain paragraph (no >)
    """
    text = doc.body

    # Remove images: ![anything](url) or ![](url)
    text = re.sub(r"!\[[^\]]*\]\s*\([^)]+\)", "", text)

    # Remove or simplify video embeds (e.g. bare vimeo/youtube link on its own line)
    text = re.sub(r"https?://(?:www\.)?(?:vimeo\.com|youtube\.com|youtu\.be)/\S+", "", text)

    # Links: [text](url) -> text (keep description only)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Remaining bare URLs (optional: remove or keep – here we remove for cleanliness)
    text = re.sub(r"https?://\S+", "", text)

    # Code blocks: ```...``` -> placeholder (Polish for spoken output)
    def _replace_code_block(match: re.Match) -> str:
        content = match.group(1).strip()
        if len(content) > 200:
            return "\n[W tym miejscu autor przedstawia fragment kodu – w wersji audio pomijamy szczegóły.]\n"
        return "\n[Fragment kodu.]\n"

    # Code block: optional ```lang, then content until closing ```
    text = re.sub(r"```(?:\w*\n)?([\s\S]*?)```", _replace_code_block, text)
    # Inline code `x` -> keep as text (backticks removed)
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Headers: ## Text -> Text (no #)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"\1", text, flags=re.MULTILINE)

    # Bold / italic: **x** -> x, *x* -> x, __x__ -> x
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)

    # Blockquotes: > line -> line
    text = re.sub(r"^>\s*(.+)$", r"\1", text, flags=re.MULTILINE)

    # Lists: - item or * item -> keep (model can turn into narration)

    # Multiple whitespace / blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.strip()

    return text


def get_clean_text_for_script(doc: MarkdownDocument) -> str:
    """
    Return cleaned text ready for step 2 (script_writer).
    Optionally prepend title from frontmatter so the model knows the episode topic.
    """
    clean = clean_markdown(doc)
    title = (doc.frontmatter or {}).get("title")
    if title:
        return f"Tytuł materiału: {title}\n\n{clean}"
    return clean
