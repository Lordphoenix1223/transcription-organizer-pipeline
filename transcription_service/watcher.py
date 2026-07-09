from __future__ import annotations

import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers.polling import PollingObserver

from .audio import build_transcript_filename, derive_meeting_name, is_recording_file, recording_timestamp
from .store import JobStore


class RecordingEventHandler(FileSystemEventHandler):
    def __init__(self, recordings_root: Path, store: JobStore, logger: logging.Logger) -> None:
        super().__init__()
        self._recordings_root = recordings_root
        self._store = store
        self._logger = logger

    def on_created(self, event) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._maybe_register(Path(event.src_path))

    def on_moved(self, event) -> None:  # type: ignore[override]
        if not event.is_directory:
            self._maybe_register(Path(event.dest_path))

    def _maybe_register(self, path: Path) -> None:
        if not is_recording_file(path):
            return

        stat = path.stat()
        meeting_name = derive_meeting_name(path, self._recordings_root)
        recording_date = recording_timestamp(path).isoformat()
        transcript_filename = build_transcript_filename(path, recording_timestamp(path))
        self._store.upsert_source(
            source_path=path.resolve(),
            source_mtime_ns=stat.st_mtime_ns,
            source_size=stat.st_size,
            meeting_name=meeting_name,
            recording_date=recording_date,
            transcript_filename=transcript_filename,
        )
        self._logger.info("Queued recording: %s", path)


class RecordingWatcher:
    def __init__(self, recordings_root: Path, store: JobStore, logger: logging.Logger) -> None:
        self._recordings_root = recordings_root
        self._store = store
        self._logger = logger
        self._observer = PollingObserver(timeout=1.0)
        self._handler = RecordingEventHandler(recordings_root, store, logger)

    def start(self) -> None:
        self._observer.schedule(self._handler, str(self._recordings_root), recursive=True)
        self._observer.start()
        self._logger.info("Watching %s for new recordings", self._recordings_root)

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=10)
