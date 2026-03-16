"""
Generate MP3 files from final script via OpenAI TTS.
Long scripts are split into chunks (by paragraphs), each chunk → separate MP3, then concatenated.
"""

import logging
import tempfile
import subprocess
from pathlib import Path

from openai import OpenAI

from . import config
from .utils import retry_with_backoff

logger = logging.getLogger(__name__)

# Instruction for TTS: natural voice, clear Polish (OpenAI recommends cedar/marin)
TTS_INSTRUCTIONS = (
    "Mów po polsku, wyraźnie i naturalnie. Ton ciepły, pewny, jak doświadczony wykładowca. "
    "Umiarkowane tempo, krótkie pauzy między zdaniami. Artykulacja wyraźna, bez pośpiechu. "
    "Brzmij ludzko i żywo, nie mechanicznie."
)


def _split_script_into_chunks(text: str, max_chars: int) -> list[str]:
    """
    Split script into chunks no longer than max_chars.
    Split at paragraphs (double newline) or single newline, not mid-sentence.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_chars:
            chunks.append(remaining.strip())
            break
        # Find split point: first \n\n, then \n, within max_chars
        block = remaining[: max_chars + 1]
        split_at = -1
        for sep in ("\n\n", "\n", ". ", " "):
            pos = block.rfind(sep)
            if pos > max_chars // 2:  # don't split too early
                split_at = pos + len(sep)
                break
        if split_at <= 0:
            split_at = max_chars
        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()
    return chunks


def _generate_one_chunk_mp3(
    client: OpenAI,
    chunk: str,
    out_path: Path,
) -> None:
    """Generate one MP3 file from a text fragment."""
    def _request() -> None:
        response = client.audio.speech.create(
            model=config.TTS_MODEL,
            voice=config.TTS_VOICE,
            input=chunk,
            instructions=TTS_INSTRUCTIONS,
            response_format="mp3",
        )
        out_path.write_bytes(response.content)

    retry_with_backoff(_request, log=logger)


def _concat_mp3_files(file_paths: list[Path], output_path: Path) -> None:
    """
    Concatenate MP3 files into one using ffmpeg (concat demuxer).
    Requires ffmpeg in PATH.
    """
    if not file_paths:
        raise ValueError("No files to concatenate")
    if len(file_paths) == 1:
        import shutil
        shutil.copy2(file_paths[0], output_path)
        return

    list_file = output_path.with_suffix(".concat_list.txt")
    try:
        # ffmpeg concat demuxer: each line is "file 'path'"
        lines = [f"file '{p.resolve().as_posix()}'" for p in file_paths]
        list_file.write_text("\n".join(lines), encoding="utf-8")
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {result.stderr or result.stdout}")
    finally:
        if list_file.exists():
            list_file.unlink(missing_ok=True)


def generate_audio_for_script(
    script_path: Path,
    output_audio_dir: Path,
    client: OpenAI,
    force: bool = False,
) -> tuple[bool, str | None]:
    """
    Read script from script_path, generate MP3 into output_audio_dir (same base name, .mp3).
    Returns (success, path_to_mp3 or None).
    """
    slug = script_path.stem
    mp3_path = output_audio_dir / f"{slug}.mp3"
    if mp3_path.exists() and not force:
        logger.info("Audio file already exists (skipping): %s", mp3_path)
        return True, str(mp3_path)

    try:
        script_text = script_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("Cannot read script %s: %s", script_path, e)
        return False, None

    script_text = script_text.strip()
    if not script_text:
        logger.error("Empty script: %s", script_path)
        return False, None

    max_chars = config.MAX_SCRIPT_CHARS_PER_CHUNK
    chunks = _split_script_into_chunks(script_text, max_chars)
    if not chunks:
        return False, None

    output_audio_dir.mkdir(parents=True, exist_ok=True)
    temp_files: list[Path] = []

    try:
        for i, chunk in enumerate(chunks):
            tmp = Path(tempfile.gettempdir()) / f"podcast_{slug}_{i}.mp3"
            _generate_one_chunk_mp3(client, chunk, tmp)
            temp_files.append(tmp)

        if len(temp_files) == 1:
            temp_files[0].rename(mp3_path)
        else:
            _concat_mp3_files(temp_files, mp3_path)
        logger.info("Saved audio: %s", mp3_path)
        return True, str(mp3_path)
    except Exception as e:
        logger.exception("Audio generation failed for %s: %s", script_path, e)
        return False, None
    finally:
        for f in temp_files:
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass
