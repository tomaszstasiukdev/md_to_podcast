"""
Helpers: slug from filename, logging, retry for HTTP.
"""

import logging
import re
import time
from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")


def slug_from_path(file_path: Path) -> str:
    """
    Return slug (name without extension) from file path.
    E.g. 's01e01-programowanie-....md' -> 's01e01-programowanie-....'
    """
    return file_path.stem


def setup_logging(level: str = "INFO") -> None:
    """Configure logging to stderr with given level."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def retry_with_backoff(
    fn: Callable[[], T],
    max_attempts: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    log: logging.Logger | None = None,
) -> T:
    """
    Run fn(). On exception (e.g. HTTP error) retry with delay.
    """
    logger = log or logging.getLogger(__name__)
    last_exc = None
    delay = initial_delay
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < max_attempts:
                logger.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.1f s.",
                    attempt,
                    max_attempts,
                    e,
                    delay,
                )
                time.sleep(delay)
                delay *= backoff_factor
            else:
                logger.error("All %d attempts failed.", max_attempts)
    raise last_exc  # type: ignore


def count_urls(text: str) -> int:
    """Count approximate number of URLs in text (http/https)."""
    return len(re.findall(r"https?://\S+", text))


def count_markdown_artifacts(text: str) -> int:
    """Count typical markdown artifacts: ##, **, [], ```."""
    pattern = r"(^#{1,6}\s|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\)|```)"
    return len(re.findall(pattern, text, re.MULTILINE))
