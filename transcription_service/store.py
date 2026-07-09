from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RecordingJob:
    id: int
    source_path: str
    source_mtime_ns: int
    source_size: int
    meeting_name: str
    recording_date: str
    transcript_filename: str
    retries: int
    next_attempt_at: str
    status: str
    last_error: Optional[str]

    @property
    def path(self) -> Path:
        return Path(self.source_path)


class JobStore:
    def __init__(self, db_path: Path, metadata_path: Path) -> None:
        self._db_path = db_path
        self._metadata_path = metadata_path
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA synchronous=NORMAL;")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_path TEXT NOT NULL UNIQUE,
                    source_mtime_ns INTEGER NOT NULL,
                    source_size INTEGER NOT NULL,
                    meeting_name TEXT NOT NULL,
                    recording_date TEXT NOT NULL,
                    transcript_filename TEXT NOT NULL,
                    retries INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL DEFAULT '1970-01-01T00:00:00+00:00',
                    status TEXT NOT NULL DEFAULT 'pending',
                    last_error TEXT,
                    transcript_path TEXT,
                    transcript_text TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )

    def recover_in_progress_jobs(self) -> None:
        with self._lock, self._connect() as connection:
            now = utc_now_iso()
            connection.execute(
                """
                UPDATE jobs
                SET status = 'retry',
                    next_attempt_at = ?,
                    last_error = COALESCE(last_error, 'Recovered after service restart'),
                    updated_at = ?
                WHERE status = 'processing'
                """,
                (now, now),
            )

    def mark_permanent_failure(self, job_id: int, error_message: str) -> None:
        with self._lock, self._connect() as connection:
            now = utc_now_iso()
            connection.execute(
                """
                UPDATE jobs
                SET status = 'failed',
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (error_message, now, job_id),
            )

    def upsert_source(
        self,
        source_path: Path,
        source_mtime_ns: int,
        source_size: int,
        meeting_name: str,
        recording_date: str,
        transcript_filename: str,
    ) -> None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT id, source_mtime_ns, source_size, status FROM jobs WHERE source_path = ?",
                (str(source_path),),
            ).fetchone()
            now = utc_now_iso()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO jobs (
                        source_path, source_mtime_ns, source_size, meeting_name, recording_date,
                        transcript_filename, retries, next_attempt_at, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, 'pending', ?, ?)
                    """,
                    (
                        str(source_path),
                        source_mtime_ns,
                        source_size,
                        meeting_name,
                        recording_date,
                        transcript_filename,
                        now,
                        now,
                        now,
                    ),
                )
                return

            if row["source_mtime_ns"] != source_mtime_ns or row["source_size"] != source_size:
                connection.execute(
                    """
                    UPDATE jobs
                    SET source_mtime_ns = ?, source_size = ?, meeting_name = ?, recording_date = ?,
                        transcript_filename = ?, retries = 0, next_attempt_at = ?, status = 'pending',
                        last_error = NULL, updated_at = ?, completed_at = NULL, transcript_path = NULL,
                        transcript_text = NULL
                    WHERE source_path = ?
                    """,
                    (
                        source_mtime_ns,
                        source_size,
                        meeting_name,
                        recording_date,
                        transcript_filename,
                        now,
                        now,
                        str(source_path),
                    ),
                )

    def claim_next_job(self) -> Optional[RecordingJob]:
        with self._lock, self._connect() as connection:
            now = utc_now_iso()
            row = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE status IN ('pending', 'retry')
                  AND next_attempt_at <= ?
                ORDER BY datetime(created_at) ASC, id ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                "UPDATE jobs SET status = 'processing', updated_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            return self._row_to_job(row)

    def mark_completed(self, job_id: int, transcript_path: Path, transcript_text: str) -> None:
        with self._lock, self._connect() as connection:
            now = utc_now_iso()
            connection.execute(
                """
                UPDATE jobs
                SET status = 'completed',
                    transcript_path = ?,
                    transcript_text = ?,
                    last_error = NULL,
                    updated_at = ?,
                    completed_at = ?
                WHERE id = ?
                """,
                (str(transcript_path), transcript_text, now, now, job_id),
            )

    def mark_failed(self, job_id: int, error_message: str, next_attempt_at: str) -> None:
        with self._lock, self._connect() as connection:
            now = utc_now_iso()
            connection.execute(
                """
                UPDATE jobs
                SET status = 'retry',
                    retries = retries + 1,
                    last_error = ?,
                    next_attempt_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (error_message, next_attempt_at, now, job_id),
            )

    def pending_jobs(self) -> Iterable[RecordingJob]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM jobs
                WHERE status IN ('pending', 'retry', 'processing')
                ORDER BY datetime(created_at) ASC, id ASC
                """
            ).fetchall()
            return [self._row_to_job(row) for row in rows]

    def append_metadata_record(
        self,
        meeting_name: str,
        recording_date: str,
        transcript_filename: str,
        original_filename: Optional[str] = None,
        output_directory: Optional[str] = None,
        analysis_filename: Optional[str] = None,
        analysis_json_filename: Optional[str] = None,
    ) -> None:
        record = {
            "meeting_name": meeting_name,
            "recording_date": recording_date,
            "transcript_filename": transcript_filename,
            "written_at": utc_now_iso(),
        }
        if original_filename:
            record["original_filename"] = original_filename
        if output_directory:
            record["output_directory"] = output_directory
        if analysis_filename:
            record["analysis_filename"] = analysis_filename
        if analysis_json_filename:
            record["analysis_json_filename"] = analysis_json_filename
        with self._lock:
            with self._metadata_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _row_to_job(self, row: sqlite3.Row) -> RecordingJob:
        return RecordingJob(
            id=row["id"],
            source_path=row["source_path"],
            source_mtime_ns=row["source_mtime_ns"],
            source_size=row["source_size"],
            meeting_name=row["meeting_name"],
            recording_date=row["recording_date"],
            transcript_filename=row["transcript_filename"],
            retries=row["retries"],
            next_attempt_at=row["next_attempt_at"],
            status=row["status"],
            last_error=row["last_error"],
        )
