"""
Application configuration from .env and environment variables.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env: first project dir (parent of podcast_generator), then cwd
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
load_dotenv(_ENV_PATH)
load_dotenv()  # fallback: .env in current working directory


def _str(value: str | None, default: str = "") -> str:
    if value is None:
        return default
    s = (value or "").strip()
    return s if s else default


def _path(value: str | None, default: Path) -> Path:
    s = _str(value)
    if not s:
        return default
    p = Path(s)
    return p.expanduser().resolve() if not p.is_absolute() else p


# --- Configuration variables ---

OPENAI_API_KEY = _str(os.environ.get("OPENAI_API_KEY"))
INPUT_DIR = _path(os.environ.get("INPUT_DIR"), _PROJECT_ROOT / "md")
OUTPUT_DIR = _path(os.environ.get("OUTPUT_DIR"), _PROJECT_ROOT / "output")

# Output subdirs (relative to OUTPUT_DIR)
SCRIPTS_DIR_NAME = "scripts"
AUDIO_DIR_NAME = "audio"
MERGED_DIR_NAME = "merged"

SCRIPT_MODEL = _str(os.environ.get("SCRIPT_MODEL"), "gpt-4o-mini")
TTS_MODEL = _str(os.environ.get("TTS_MODEL"), "gpt-4o-mini-tts")
# Default cedar or marin – OpenAI recommends for best quality; onyx/echo can sound more robotic
TTS_VOICE = _str(os.environ.get("TTS_VOICE"), "cedar")

# Max length of one TTS chunk (characters). API limit ~2000 tokens; ~4000 chars is a safe value.
def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


MAX_SCRIPT_CHARS_PER_CHUNK = _int_env("MAX_SCRIPT_CHARS_PER_CHUNK", 4000)

LOG_LEVEL = _str(os.environ.get("LOG_LEVEL"), "INFO").upper()

# Script generation: how many sections per API call (fewer = smaller batches, better 1:1 detail)
SECTIONS_PER_BATCH = _int_env("SECTIONS_PER_BATCH", 2)
# Min ratio of script length to source length (below = expand). 0.6 = script at least ~60% of source (near 1:1).
MIN_SCRIPT_TO_SOURCE_RATIO = _float_env("MIN_SCRIPT_TO_SOURCE_RATIO", 0.6)
# After each batch, compare script to source and append missing content (1=on, 0=off, fewer API calls)
CHECK_COMPLETENESS_AFTER_BATCH = os.environ.get("CHECK_COMPLETENESS_AFTER_BATCH", "1").strip() in ("1", "true", "yes")
# Second pass (draft + fill): after full script, compare to source and append missing (1=on, 0=off)
FILL_MISSING_FULL_PASS = os.environ.get("FILL_MISSING_FULL_PASS", "1").strip() in ("1", "true", "yes")

# Derived paths
def get_scripts_dir(base: Path | None = None) -> Path:
    root = base or OUTPUT_DIR
    return root / SCRIPTS_DIR_NAME


def get_audio_dir(base: Path | None = None) -> Path:
    root = base or OUTPUT_DIR
    return root / AUDIO_DIR_NAME


def get_merged_dir(base: Path | None = None) -> Path:
    root = base or OUTPUT_DIR
    return root / MERGED_DIR_NAME
