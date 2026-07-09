#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

exec "$PYTHON_BIN" - "$ROOT_DIR" <<'PY'
import json
import logging
import sys
from pathlib import Path

from transcription_service.analysis import analyze_transcript
from transcription_service.config import load_config
from transcription_service.field_extractor import extract_interview_fields
from transcription_service.notion_integration import NotionUpdater

root = Path(sys.argv[1])
transcripts_root = root / "Transcripts"
transcript_files = sorted(transcripts_root.rglob("transcript.txt"), key=lambda p: p.stat().st_mtime)
if not transcript_files:
    raise SystemExit("No transcript.txt files found in Transcripts/.")

transcript_path = transcript_files[-1]
bundle_dir = transcript_path.parent
transcript_text = transcript_path.read_text(encoding="utf-8").strip()
if not transcript_text:
    raise SystemExit(f"Transcript is empty: {transcript_path}")

config = load_config(str(root))
metadata_path = transcripts_root / "metadata.jsonl"
recording_date = None
meeting_name = bundle_dir.name.split("_", 1)[0]
transcript_metadata = {
    "bundle_name": bundle_dir.name,
    "original_filename": None,
    "output_directory": bundle_dir.name,
}
if metadata_path.exists():
    for line in reversed(metadata_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("output_directory") == bundle_dir.name:
            recording_date = record.get("recording_date")
            meeting_name = record.get("meeting_name") or meeting_name
            transcript_metadata.update(record)
            transcript_metadata["bundle_name"] = bundle_dir.name
            transcript_metadata["output_directory"] = record.get("output_directory") or bundle_dir.name
            break
if transcript_metadata.get("original_filename") is None:
    transcript_metadata["original_filename"] = transcript_path.name

logger = logging.getLogger("reprocess_latest_transcript")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)

analysis = analyze_transcript(transcript_text, logger)
extraction = extract_interview_fields(
    transcript=transcript_text,
    analysis=analysis,
    recording_date=recording_date,
    title=meeting_name,
)

def write_text_atomic(path: Path, content: str) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(content.rstrip() + "\n", encoding="utf-8")
    tmp_path.replace(path)


def write_json_atomic(path: Path, payload) -> None:
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp_path.replace(path)


analysis_md_path = bundle_dir / "analysis.md"
analysis_json_path = bundle_dir / "analysis.json"
qa_pairs_path = bundle_dir / "qa_pairs.json"
field_extraction_path = bundle_dir / "field_extraction.json"

write_text_atomic(analysis_md_path, analysis.to_markdown())
write_json_atomic(analysis_json_path, analysis.to_dict())
write_json_atomic(qa_pairs_path, extraction.qa_pairs)
write_json_atomic(field_extraction_path, extraction.to_dict())

if config.enable_notion:
    updater = NotionUpdater(config, logger)
    row_id = updater.publish_interview_row(
        title=meeting_name,
        transcript=transcript_text,
        transcript_filename=transcript_path.name,
        analysis=analysis,
        recording_date=recording_date,
        extraction=extraction,
        transcript_bundle_name=bundle_dir.name,
        transcript_metadata=transcript_metadata,
        fallback_timestamp=recording_date,
    )
    print(row_id)
else:
    print("Rebuilt local outputs only. ENABLE_NOTION=false, so nothing was published.")
PY
