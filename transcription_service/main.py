from __future__ import annotations

import argparse
import json
import logging
import signal
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .analysis import analyze_transcript
from .audio import (
    build_chunk_ranges,
    build_transcript_filename,
    build_transcript_output_dir,
    convert_to_riva_wav,
    derive_meeting_name,
    extract_wav_chunk,
    is_recording_file,
    probe_audio_duration_seconds,
    recording_timestamp,
    wait_for_stable_file,
)
from .config import AppConfig, load_config
from .field_extractor import extract_interview_fields
from .nvidia_client import NvidiaTranscriber
from .notion_integration import NotionUpdater
from .store import JobStore
from .watcher import RecordingWatcher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch local recordings and transcribe them with NVIDIA Whisper Large v3.")
    parser.add_argument("--base-dir", default=None, help="Repository root. Defaults to the current package root.")
    return parser.parse_args()


def configure_logging(config: AppConfig) -> logging.Logger:
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = config.logs_dir / "transcription.log"

    logger = logging.getLogger("transcription_pipeline")
    logger.setLevel(getattr(logging, config.log_level, logging.INFO))
    logger.handlers.clear()

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    logger.propagate = False
    return logger


def ensure_directories(config: AppConfig) -> None:
    for directory in [config.recordings_dir, config.transcripts_dir, config.logs_dir]:
        directory.mkdir(parents=True, exist_ok=True)


def retry_backoff_seconds(retry_count: int, base: float, maximum: float) -> float:
    delay = base * (2 ** max(0, retry_count - 1))
    return min(delay, maximum)


def write_text_atomic(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(content.rstrip() + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def write_json_atomic(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.replace(path)
    return path


def _transcribe_audio_chunks(
    transcriber: NvidiaTranscriber,
    wav_path: Path,
    logger: logging.Logger,
) -> tuple[str, list[dict[str, object]], float, int]:
    duration_seconds = probe_audio_duration_seconds(wav_path)
    logger.info("Original WAV duration: %.2f seconds", duration_seconds)

    chunk_ranges = build_chunk_ranges(duration_seconds)
    logger.info("Starting chunk transcription")
    logger.info("Transcribing audio in %d chunk(s)", len(chunk_ranges))

    chunk_metadata: list[dict[str, object]] = []
    transcript_parts: list[str] = []

    with tempfile.TemporaryDirectory(prefix="interview-audio-chunks-") as chunk_dir:
        chunk_dir_path = Path(chunk_dir)
        for index, (start_seconds, end_seconds) in enumerate(chunk_ranges, start=1):
            chunk_path = chunk_dir_path / f"chunk_{index:03d}.wav"
            chunk_duration = max(0.0, end_seconds - start_seconds)
            logger.info(
                "Chunk %d/%d: start=%.2f end=%.2f duration=%.2f",
                index,
                len(chunk_ranges),
                start_seconds,
                end_seconds,
                chunk_duration,
            )
            extract_wav_chunk(wav_path, chunk_path, start_seconds, chunk_duration)

            status = "success"
            error_message = None
            transcript_text = ""
            try:
                transcript_text = transcriber.transcribe_wav(chunk_path).strip()
                if not transcript_text:
                    status = "empty"
                else:
                    transcript_parts.append(transcript_text)
            except Exception as exc:
                status = "failed"
                error_message = str(exc)
                logger.exception("Chunk %d transcription failed", index)

            chunk_metadata.append(
                {
                    "chunk_number": index,
                    "start_time_seconds": round(start_seconds, 3),
                    "end_time_seconds": round(end_seconds, 3),
                    "transcript_length": len(transcript_text),
                    "status": status,
                    **({"error": error_message} if error_message else {}),
                }
            )
            logger.info("Chunk %d status: %s", index, status)

    combined_transcript = "\n\n".join(part.strip() for part in transcript_parts if part.strip()).strip()
    logger.info("All chunks transcribed")
    logger.info("Combined full transcript length: %d characters", len(combined_transcript))
    return combined_transcript, chunk_metadata, duration_seconds, len(chunk_ranges)


def process_job(
    job_store: JobStore,
    transcriber: NvidiaTranscriber,
    notion_updater: NotionUpdater | None,
    config: AppConfig,
    logger: logging.Logger,
    job,
) -> None:
    source_path = Path(job.source_path)
    logger.info("Processing recording: %s", source_path)

    wait_for_stable_file(source_path, config.file_settle_seconds)

    with tempfile.TemporaryDirectory(prefix="interview-transcription-") as temp_dir:
        wav_path = Path(temp_dir) / f"{source_path.stem}.wav"
        convert_to_riva_wav(source_path, wav_path)
        transcript_text, chunk_metadata, duration_seconds, chunk_count = _transcribe_audio_chunks(transcriber, wav_path, logger)
        if not transcript_text:
            raise RuntimeError("NVIDIA ASR returned an empty transcript.")

    recording_dt = datetime.fromisoformat(job.recording_date)
    output_dir = build_transcript_output_dir(source_path, recording_dt, job.meeting_name, config.transcripts_dir)
    transcript_path = output_dir / job.transcript_filename
    analysis_md_path = output_dir / "analysis.md"
    analysis_json_path = output_dir / "analysis.json"
    chunk_metadata_path = output_dir / "chunk_metadata.json"
    qa_pairs_path = output_dir / "qa_pairs.json"
    field_extraction_path = output_dir / "field_extraction.json"

    logger.info("Starting full-transcript analysis")
    analysis = analyze_transcript(transcript_text, logger)
    extraction = extract_interview_fields(
        transcript=transcript_text,
        analysis=analysis,
        recording_date=job.recording_date,
        title=job.meeting_name,
    )
    logger.info("Finished full-transcript analysis")

    write_text_atomic(transcript_path, transcript_text)
    write_json_atomic(chunk_metadata_path, {
        "original_audio_duration_seconds": round(duration_seconds, 3),
        "chunk_count": chunk_count,
        "chunks": chunk_metadata,
    })
    analysis_markdown = analysis.to_markdown()
    if any(chunk.get("status") == "failed" for chunk in chunk_metadata):
        failed_chunks = [str(chunk["chunk_number"]) for chunk in chunk_metadata if chunk.get("status") == "failed"]
        analysis_markdown = (
            "## Chunking Warning\n"
            f"- One or more chunks failed: {', '.join(failed_chunks)}\n"
            "- The transcript may be partial.\n\n"
            + analysis_markdown
        )
    write_text_atomic(analysis_md_path, analysis_markdown)
    write_json_atomic(analysis_json_path, analysis.to_dict())
    write_json_atomic(qa_pairs_path, extraction.qa_pairs)
    write_json_atomic(field_extraction_path, extraction.to_dict())

    if notion_updater is not None:
        logger.info("Publishing Notion row")
        notion_updater.publish_interview_row(
            title=job.meeting_name,
            transcript=transcript_text,
            transcript_filename=transcript_path.name,
            analysis=analysis,
            recording_date=job.recording_date,
            extraction=extraction,
            transcript_bundle_name=output_dir.name,
            transcript_metadata={
                "meeting_name": job.meeting_name,
                "recording_date": job.recording_date,
                "original_filename": source_path.name,
                "output_directory": output_dir.name,
            },
            fallback_timestamp=job.recording_date,
        )
    else:
        logger.info("ENABLE_NOTION=false, skipping Notion publish")
    job_store.append_metadata_record(
        meeting_name=job.meeting_name,
        recording_date=job.recording_date,
        transcript_filename=transcript_path.name,
        original_filename=source_path.name,
        output_directory=str(output_dir.relative_to(config.transcripts_dir)),
        analysis_filename=analysis_md_path.name,
        analysis_json_filename=analysis_json_path.name,
    )
    job_store.mark_completed(job.id, transcript_path, transcript_text)
    logger.info("Saved transcript bundle: %s", output_dir)


def scan_existing_recordings(config: AppConfig, store: JobStore, logger: logging.Logger) -> None:
    for path in config.recordings_dir.rglob("*"):
        if not is_recording_file(path):
            continue
        stat = path.stat()
        meeting_name = derive_meeting_name(path, config.recordings_dir)
        recording_dt = recording_timestamp(path)
        store.upsert_source(
            source_path=path.resolve(),
            source_mtime_ns=stat.st_mtime_ns,
            source_size=stat.st_size,
            meeting_name=meeting_name,
            recording_date=recording_dt.isoformat(),
            transcript_filename=build_transcript_filename(path, recording_dt),
        )
        logger.info("Discovered existing recording: %s", path)


def main() -> int:
    args = parse_args()
    config = load_config(args.base_dir)
    ensure_directories(config)
    logger = configure_logging(config)
    logger.info("Starting transcription pipeline")
    logger.info("No paid LLM APIs used.")
    logger.info("Recordings folder: %s", config.recordings_dir)
    logger.info("Transcripts folder: %s", config.transcripts_dir)
    logger.info("Notion publishing: %s", "enabled" if config.enable_notion else "disabled")

    store = JobStore(config.state_db_path, config.metadata_path)
    store.recover_in_progress_jobs()
    transcriber = NvidiaTranscriber(config)
    notion_updater = NotionUpdater(config, logger) if config.enable_notion else None
    stop_event = threading.Event()
    wake_event = threading.Event()

    def _handle_signal(signum, frame):  # noqa: ARG001
        logger.info("Received signal %s, shutting down", signum)
        stop_event.set()
        wake_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    watcher = RecordingWatcher(config.recordings_dir, store, logger)
    watcher.start()
    scan_existing_recordings(config, store, logger)
    wake_event.set()

    try:
        while not stop_event.is_set():
            job = store.claim_next_job()
            if job is None:
                wake_event.wait(timeout=config.scan_interval_seconds)
                wake_event.clear()
                continue

            try:
                process_job(store, transcriber, notion_updater, config, logger, job)
            except Exception as exc:
                attempt_number = job.retries + 1
                if attempt_number >= config.retry_max_attempts:
                    store.mark_permanent_failure(job.id, str(exc))
                    logger.exception("Failed to transcribe %s; marked permanently failed after %d attempts", job.source_path, attempt_number)
                else:
                    backoff = retry_backoff_seconds(attempt_number, config.retry_base_delay_seconds, config.retry_max_delay_seconds)
                    next_attempt = (datetime.now(timezone.utc) + timedelta(seconds=backoff)).isoformat()
                    store.mark_failed(job.id, str(exc), next_attempt)
                    logger.exception("Failed to transcribe %s; retry scheduled in %.1f seconds", job.source_path, backoff)
                wake_event.set()
            else:
                wake_event.set()
    finally:
        watcher.stop()

    logger.info("Transcription pipeline stopped")
    return 0
