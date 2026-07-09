#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi

"$PYTHON_BIN" - "$ROOT_DIR" <<'PY'
import json
import sys
from dataclasses import dataclass
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from transcription_service.analysis import HeuristicAnalysis
from transcription_service.field_extractor import FieldExtractionResult, InterviewExtraction
from transcription_service.notion_fields import NotionPropertySchema, build_notion_properties, format_notion_property, resolve_interview_title


def assert_no_none(value, path="root"):
    if value is None:
        raise SystemExit(f"Found None at {path}")
    if isinstance(value, dict):
        for key, child in value.items():
            assert_no_none(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_none(child, f"{path}[{index}]")


schema = {
    "Test Interview": NotionPropertySchema("Test Interview", "title"),
    "Transcript": NotionPropertySchema("Transcript", "rich_text"),
    "Legacy Text": NotionPropertySchema("Legacy Text", "text"),
    "PMF Score": NotionPropertySchema("PMF Score", "number"),
    "Did They Create A Video?": NotionPropertySchema("Did They Create A Video?", "checkbox"),
    "Would Pay?": NotionPropertySchema("Would Pay?", "select", options=("Yes", "No")),
    "Status": NotionPropertySchema("Status", "status", options=("Analyzed",)),
    "Interview Date": NotionPropertySchema("Interview Date", "date"),
    "Website": NotionPropertySchema("Website", "url"),
    "Email": NotionPropertySchema("Email", "email"),
    "Phone": NotionPropertySchema("Phone", "phone_number"),
    "Goal Of Video": NotionPropertySchema("Goal Of Video", "multi_select", options=("Views", "Engagement")),
}

analysis = HeuristicAnalysis(
    biggest_pain_points=["It was confusing"],
    feature_requests=["I wish it had export"],
    pricing_mentions=["$29/month"],
    positive_feedback=["It was helpful"],
    negative_confusing_feedback=["It was confusing"],
    action_items=["Follow up next week"],
    exact_quote_candidates=["It was helpful"],
    pricing_feedback=["I'd pay $29/month"],
    would_pay="Yes",
    suggested_price="$29/month",
    retention_likelihood=7,
    pmf_score=8,
)

extraction = InterviewExtraction(
    title="sample-interview-2026-06-19",
    transcript="What is your plan?\nI would pay $29/month.",
    recording_date="2026-06-19T00:00:00+00:00",
    qa_pairs=[],
    fields={
        "Test Interview": FieldExtractionResult("sample-interview-2026-06-19", 1.0, [], None, "title", True),
        "Transcript": FieldExtractionResult("What is your plan?\nI would pay $29/month.", 1.0, [], None, "transcript", True),
        "Legacy Text": FieldExtractionResult("legacy value", 1.0, [], None, "analysis", True),
        "PMF Score": FieldExtractionResult(8, 1.0, [], None, "analysis", True),
        "Did They Create A Video?": FieldExtractionResult(True, 1.0, [], None, "signals", True),
        "Would Pay?": FieldExtractionResult("Yes", 1.0, [], None, "analysis", True),
        "Status": FieldExtractionResult("Analyzed", 1.0, [], None, "analysis", True),
        "Interview Date": FieldExtractionResult("2026-06-19", 1.0, [], None, "analysis", True),
        "Website": FieldExtractionResult("https://example.com", 1.0, [], None, "analysis", True),
        "Email": FieldExtractionResult("alex@example.com", 1.0, [], None, "analysis", True),
        "Phone": FieldExtractionResult("+1 416 555 0101", 1.0, [], None, "analysis", True),
        "Goal Of Video": FieldExtractionResult(["Views", "Engagement"], 1.0, [], None, "analysis", True),
    },
    warnings=[],
)

properties = build_notion_properties(
    title="sample-interview-2026-06-19",
    transcript=extraction.transcript,
    analysis=analysis,
    recording_date="2026-06-19T00:00:00+00:00",
    extraction=extraction,
    schema=schema,
)

assert properties["Test Interview"] == {"title": [{"text": {"content": "sample-interview-2026-06-19"}}]}
assert properties["Transcript"] == {"rich_text": [{"text": {"content": "What is your plan?\nI would pay $29/month."}}]}
assert properties["Legacy Text"] == {"rich_text": [{"text": {"content": "legacy value"}}]}
assert properties["PMF Score"] == {"number": 8.0}
assert properties["Did They Create A Video?"] == {"checkbox": True}
assert properties["Would Pay?"] == {"select": {"name": "Yes"}}
assert properties["Status"] == {"status": {"name": "Analyzed"}}
assert properties["Interview Date"] == {"date": {"start": "2026-06-19"}}
assert properties["Website"] == {"url": "https://example.com"}
assert properties["Email"] == {"email": "alex@example.com"}
assert properties["Phone"] == {"phone_number": "+1 416 555 0101"}
assert properties["Goal Of Video"] == {"multi_select": [{"name": "Views"}, {"name": "Engagement"}]}
assert_no_none(properties)

resolved = resolve_interview_title(
    "",
    transcript_bundle_name="bundle-name-stem",
    transcript_metadata={"original_filename": "original-recording.mp4"},
    fallback_timestamp="2026-06-19 19:42:47 UTC",
)
if resolved != "bundle-name-stem":
    raise SystemExit(f"Fallback title resolution failed: {resolved!r}")

empty_title_schema = {"Test Interview": NotionPropertySchema("Test Interview", "title")}
empty_title_extraction = InterviewExtraction(
    title="",
    transcript="hello",
    recording_date=None,
    qa_pairs=[],
    fields={},
    warnings=[],
)
empty_title_properties = build_notion_properties(
    title="",
    transcript="hello",
    analysis=analysis,
    transcript_bundle_name="bundle-name-stem",
    transcript_metadata={"original_filename": "original-recording.mp4"},
    fallback_timestamp="2026-06-19 19:42:47 UTC",
    extraction=empty_title_extraction,
    schema=empty_title_schema,
)
if empty_title_properties["Test Interview"] != {"title": [{"text": {"content": "bundle-name-stem"}}]}:
    raise SystemExit(f"Empty title fallback failed: {empty_title_properties['Test Interview']!r}")

for name, notion_type, value in [
    ("Test Interview", "title", "abc"),
    ("Transcript", "rich_text", "hello"),
    ("PMF Score", "number", 3),
    ("Did They Create A Video?", "checkbox", True),
    ("Would Pay?", "select", "Yes"),
    ("Status", "status", "Analyzed"),
]:
    payload, message = format_notion_property(name, schema[name], value)
    if payload is None:
        raise SystemExit(f"{name} ({notion_type}) unexpectedly skipped: {message}")
    assert_no_none(payload, name)

print("PASS")
PY
