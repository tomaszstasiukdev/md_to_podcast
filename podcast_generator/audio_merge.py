"""
Merge all generated episode MP3s into one file (alphabetical order).
"""

import logging
from pathlib import Path

from . import config
from .utils import retry_with_backoff

logger = logging.getLogger(__name__)


def _concat_mp3_ffmpeg(file_paths: list[Path], output_path: Path) -> None:
    """Concatenate MP3 files via ffmpeg concat demuxer."""
    import subprocess
    if not file_paths:
        raise ValueError("No files to concatenate")
    if len(file_paths) == 1:
        import shutil
        shutil.copy2(file_paths[0], output_path)
        return
    list_file = output_path.with_suffix(".concat_list.txt")
    try:
        lines = [f"file '{p.resolve().as_posix()}'" for p in file_paths]
        list_file.write_text("\n".join(lines), encoding="utf-8")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c", "copy", str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr or result.stdout}")
    finally:
        if list_file.exists():
            list_file.unlink(missing_ok=True)


def merge_all_episodes(
    output_audio_dir: Path,
    merged_dir: Path,
    output_filename: str = "podcast_all.mp3",
) -> tuple[bool, str | None]:
    """
    Merge all .mp3 files from output_audio_dir into one file.
    Order: alphabetically by filename.
    Returns (success, path_to_merged or None). If no files, returns (False, None) and logs.
    """
    if not output_audio_dir.is_dir():
        logger.warning("Audio directory does not exist: %s", output_audio_dir)
        return False, None

    mp3_files = sorted(output_audio_dir.glob("*.mp3"))
    if not mp3_files:
        logger.warning("No MP3 files to merge in directory: %s", output_audio_dir)
        return False, None

    merged_dir.mkdir(parents=True, exist_ok=True)
    output_path = merged_dir / output_filename

    def _do_merge() -> None:
        _concat_mp3_ffmpeg(mp3_files, output_path)

    try:
        retry_with_backoff(_do_merge, log=logger)
        logger.info("Merged %d episodes to: %s", len(mp3_files), output_path)
        return True, str(output_path)
    except Exception as e:
        logger.exception("MP3 merge failed: %s", e)
        return False, None
