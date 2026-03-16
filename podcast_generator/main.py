"""
CLI: load MD → clean → script → TTS → optionally merge all MP3.
"""

import argparse
import logging
import sys
from pathlib import Path

from openai import OpenAI

from . import config
from .config import get_scripts_dir, get_audio_dir, get_merged_dir
from .utils import setup_logging, slug_from_path
from .markdown_loader import find_and_load_markdown_files
from .script_writer import generate_script
from .tts_generator import generate_audio_for_script
from .audio_merge import merge_all_episodes

logger = logging.getLogger(__name__)


def _ensure_api_key() -> None:
    if not (config.OPENAI_API_KEY or "").strip():
        logger.error("OPENAI_API_KEY not set. Set env var or add to .env")
        sys.exit(1)


def run(
    input_dir: Path,
    output_dir: Path,
    pattern: str,
    merge_all: bool,
    skip_script: bool,
    skip_audio: bool,
    force: bool,
) -> None:
    scripts_dir = get_scripts_dir(output_dir)
    audio_dir = get_audio_dir(output_dir)
    merged_dir = get_merged_dir(output_dir)

    docs = find_and_load_markdown_files(input_dir, pattern)
    if not docs:
        logger.warning("No .md files found in %s (pattern: %s)", input_dir, pattern)
        print("No Markdown files found.")
        return

    total = len(docs)
    scripts_ok = 0
    audio_ok = 0
    errors = 0

    client = OpenAI(api_key=config.OPENAI_API_KEY) if config.OPENAI_API_KEY else None
    if not skip_script or not skip_audio:
        _ensure_api_key()
        if not client:
            return

    for doc in docs:
        slug = slug_from_path(doc.path)
        logger.info("Processing: %s", doc.filename)

        if not skip_script:
            ok, _ = generate_script(doc, client, scripts_dir, slug, force=force)
            if ok:
                scripts_ok += 1
            else:
                errors += 1
                continue

        if not skip_audio:
            script_path = scripts_dir / f"{slug}.txt"
            if not script_path.exists():
                logger.warning("No script for %s (skipping audio)", doc.filename)
                errors += 1
                continue
            ok, _ = generate_audio_for_script(script_path, audio_dir, client, force=force)
            if ok:
                audio_ok += 1
            else:
                errors += 1

    if merge_all:
        ok, path = merge_all_episodes(audio_dir, merged_dir)
        if ok:
            print(f"Merged all episodes to: {path}")
        else:
            print("Merge failed or no MP3 files.")

    # Summary
    print("\n--- Summary ---")
    print(f"Files found: {total}")
    if not skip_script:
        print(f"Scripts generated: {scripts_ok}")
    if not skip_audio:
        print(f"Audio files generated: {audio_ok}")
    print(f"Errors: {errors}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate audio podcast (MP3) from Markdown files.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=config.INPUT_DIR,
        help="Directory with .md files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=config.OUTPUT_DIR,
        help="Output directory (scripts, audio, merged)",
    )
    parser.add_argument(
        "--pattern",
        default="*.md",
        help="Glob pattern for .md files",
    )
    parser.add_argument(
        "--merge-all",
        action="store_true",
        help="At the end merge all episodes into one MP3 (alphabetical order)",
    )
    parser.add_argument(
        "--skip-script",
        action="store_true",
        help="Skip script generation (use existing .txt)",
    )
    parser.add_argument(
        "--skip-audio",
        action="store_true",
        help="Skip audio generation (scripts only)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .txt and .mp3 files",
    )
    parser.add_argument(
        "--log-level",
        default=config.LOG_LEVEL,
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        help="Log level",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    run(
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        pattern=args.pattern,
        merge_all=args.merge_all,
        skip_script=args.skip_script,
        skip_audio=args.skip_audio,
        force=args.force,
    )


if __name__ == "__main__":
    main()
