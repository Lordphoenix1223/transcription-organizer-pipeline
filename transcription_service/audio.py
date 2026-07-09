from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
import wave
from datetime import datetime
from pathlib import Path

SUPPORTED_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".ogg",
    ".wav",
    ".webm",
}


def is_recording_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def sanitize_filename_part(value: str) -> str:
    cleaned = re.sub(r"[^\w\s.-]+", "", value, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", "_", cleaned.strip())
    cleaned = re.sub(r"_{2,}", "_", cleaned)
    return cleaned.strip("._") or "recording"


def derive_meeting_name(recording_path: Path, recordings_root: Path) -> str:
    try:
        relative_parent = recording_path.parent.resolve().relative_to(recordings_root.resolve())
    except ValueError:
        relative_parent = None

    if relative_parent and str(relative_parent) != ".":
        return sanitize_filename_part(relative_parent.parts[0])

    stem = recording_path.stem
    stem = re.sub(r"(?i)^zoom[\s_-]*", "", stem)
    stem = re.sub(r"(?i)[\s_-]*recording.*$", "", stem)
    return sanitize_filename_part(stem)


def recording_timestamp(recording_path: Path) -> datetime:
    return datetime.fromtimestamp(recording_path.stat().st_mtime)


def build_transcript_filename(recording_path: Path, recording_dt: datetime) -> str:
    return "transcript.txt"


def build_transcript_output_dir(recording_path: Path, recording_dt: datetime, meeting_name: str, transcripts_root: Path) -> Path:
    meeting_slug = sanitize_filename_part(meeting_name)
    source_slug = sanitize_filename_part(recording_path.stem)
    timestamp = recording_dt.strftime("%Y%m%dT%H%M%S")
    source_hash = hashlib.sha1(str(recording_path.resolve()).encode("utf-8")).hexdigest()[:8]
    return transcripts_root / f"{meeting_slug}_{source_slug}_{timestamp}_{source_hash}"


def wait_for_stable_file(path: Path, settle_seconds: float, timeout_seconds: float = 1800.0) -> None:
    start = time.monotonic()
    last_size = -1
    stable_since = None

    while True:
        if not path.exists():
            raise FileNotFoundError(f"Recording disappeared before it stabilized: {path}")

        size = path.stat().st_size
        now = time.monotonic()
        if size == last_size:
            stable_since = stable_since or now
            if now - stable_since >= settle_seconds:
                return
        else:
            last_size = size
            stable_since = now

        if now - start > timeout_seconds:
            raise TimeoutError(f"Timed out waiting for file to stabilize: {path}")

        time.sleep(min(1.0, max(0.2, settle_seconds / 5)))


def convert_to_riva_wav(source_path: Path, destination_path: Path) -> Path:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required but was not found on PATH.")

    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(destination_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg conversion failed: "
            + (result.stderr.strip() or result.stdout.strip() or "unknown error")
        )
    return destination_path


def probe_audio_duration_seconds(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        command = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout or "{}")
                duration = float(payload["format"]["duration"])
                if duration > 0:
                    return duration
            except Exception:
                pass

    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as wav_file:
            frames = wav_file.getnframes()
            framerate = wav_file.getframerate()
            if framerate <= 0:
                raise RuntimeError(f"Could not determine WAV duration for {path}.")
            return frames / float(framerate)

    raise RuntimeError(f"Could not determine duration for {path}. Install ffprobe or use a WAV file.")


def extract_wav_chunk(source_path: Path, destination_path: Path, start_seconds: float, duration_seconds: float) -> Path:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required but was not found on PATH.")

    command = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-i",
        str(source_path),
        "-t",
        f"{duration_seconds:.3f}",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(destination_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "ffmpeg chunk extraction failed: "
            + (result.stderr.strip() or result.stdout.strip() or "unknown error")
        )
    return destination_path


def build_chunk_ranges(duration_seconds: float, chunk_length_seconds: float = 240.0, overlap_seconds: float = 5.0) -> list[tuple[float, float]]:
    if duration_seconds <= 0:
        return [(0.0, 0.0)]
    if duration_seconds <= 300.0:
        return [(0.0, duration_seconds)]

    step_seconds = max(1.0, chunk_length_seconds - overlap_seconds)
    ranges: list[tuple[float, float]] = []
    start = 0.0
    while start < duration_seconds:
        end = min(start + chunk_length_seconds, duration_seconds)
        ranges.append((start, end))
        if end >= duration_seconds:
            break
        start += step_seconds
    return ranges
