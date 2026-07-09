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
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root))

from transcription_service.analysis import analyze_transcript
from transcription_service.field_extractor import extract_interview_fields
from transcription_service.notion_fields import NotionPropertySchema, build_notion_properties

fixtures = {
    "current_spend": root / "tests" / "sample_interview_current_spend.txt",
    "pricing": root / "tests" / "sample_interview_pricing.txt",
    "confusion": root / "tests" / "sample_interview_confusion.txt",
}

output_dir = root / "tests" / "output_field_extraction"
output_dir.mkdir(parents=True, exist_ok=True)

results = {}
schema = {
    "Test Interview": NotionPropertySchema("Test Interview", "title"),
    "Transcript": NotionPropertySchema("Transcript", "rich_text"),
    "Analysis": NotionPropertySchema("Analysis", "rich_text"),
    "Biggest Pain Points": NotionPropertySchema("Biggest Pain Points", "rich_text"),
    "Feature Requests": NotionPropertySchema("Feature Requests", "rich_text"),
    "Positive Feedback": NotionPropertySchema("Positive Feedback", "rich_text"),
    "Pricing Feedback": NotionPropertySchema("Pricing Feedback", "rich_text"),
    "Action Items": NotionPropertySchema("Action Items", "rich_text"),
    "Key Quotes": NotionPropertySchema("Key Quotes", "rich_text"),
    "PMF Score": NotionPropertySchema("PMF Score", "number"),
    "Retention Likelihood": NotionPropertySchema("Retention Likelihood", "number"),
    "Suggested Price": NotionPropertySchema("Suggested Price", "rich_text"),
    "Would Pay?": NotionPropertySchema("Would Pay?", "select", options=("Yes", "No")),
    "Status": NotionPropertySchema("Status", "status", options=("Analyzed",)),
    "Current Tools": NotionPropertySchema("Current Tools", "rich_text"),
    "Monthly Tool Spend": NotionPropertySchema("Monthly Tool Spend", "rich_text"),
    "Platform": NotionPropertySchema("Platform", "select", options=("TikTok", "Instagram Reels", "YouTube Shorts", "LinkedIn", "Multiple")),
    "Posts Per Week": NotionPropertySchema("Posts Per Week", "number"),
    "Goal Of Video": NotionPropertySchema("Goal Of Video", "multi_select", options=("Views", "Engagement", "Followers", "Brand Awareness", "Sales", "Client Approval")),
    "Current Review Process": NotionPropertySchema("Current Review Process", "rich_text"),
    "Biggest Uncertainty": NotionPropertySchema("Biggest Uncertainty", "rich_text"),
    "Most Valuable Output": NotionPropertySchema("Most Valuable Output", "rich_text"),
    "Least Valuable Output": NotionPropertySchema("Least Valuable Output", "rich_text"),
    "What Changed?": NotionPropertySchema("What Changed?", "rich_text"),
    "Would Use On Next Video?": NotionPropertySchema("Would Use On Next Video?", "select", options=("Definitely", "Probably", "Maybe", "Unlikely", "No")),
    "Did The Tool Change The Output?": NotionPropertySchema("Did The Tool Change The Output?", "select", options=("Yes - Major Changes", "Yes - Minor Changes", "No Changes", "Gave Confidence Only")),
    "Did They Understand The Tool Quickly?": NotionPropertySchema("Did They Understand The Tool Quickly?", "select", options=("Yes", "Mostly", "Somewhat", "Confused", "Very Confused")),
    "Where Did They Get Confused?": NotionPropertySchema("Where Did They Get Confused?", "rich_text"),
    "Did They Complete Onboarding?": NotionPropertySchema("Did They Complete Onboarding?", "checkbox"),
    "Did They Create A Video?": NotionPropertySchema("Did They Create A Video?", "checkbox"),
    "Did They Use A Prompt?": NotionPropertySchema("Did They Use A Prompt?", "checkbox"),
    "Expected Price": NotionPropertySchema("Expected Price", "rich_text"),
    "Max Price": NotionPropertySchema("Max Price", "rich_text"),
    "Referral Offered?": NotionPropertySchema("Referral Offered?", "checkbox"),
    "Follow-Up Booked?": NotionPropertySchema("Follow-Up Booked?", "checkbox"),
    "Follow-Up Actions": NotionPropertySchema("Follow-Up Actions", "rich_text"),
    "User Type": NotionPropertySchema("User Type", "select", options=("Creator", "Agency", "Brand", "Editor", "Marketing Team")),
    "Video Used": NotionPropertySchema("Video Used", "rich_text"),
    "Pain Score": NotionPropertySchema("Pain Score", "number"),
    "Disappointment Score": NotionPropertySchema("Disappointment Score", "number"),
    "Interview Date": NotionPropertySchema("Interview Date", "date"),
}
for name, path in fixtures.items():
    transcript = path.read_text(encoding="utf-8").strip()
    analysis = analyze_transcript(transcript)
    extraction = extract_interview_fields(transcript=transcript, analysis=analysis, title=name.title())
    properties = build_notion_properties(
        title=name.title(),
        transcript=transcript,
        analysis=analysis,
        extraction=extraction,
        schema=schema,
    )
    (output_dir / f"{name}.qa_pairs.json").write_text(json.dumps(extraction.qa_pairs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / f"{name}.field_extraction.json").write_text(json.dumps(extraction.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    results[name] = {
        "analysis": analysis.to_dict(),
        "extraction": extraction.to_dict(),
        "properties": properties,
    }

current_spend = results["current_spend"]["extraction"]["fields"]["Monthly Tool Spend"]["value"]
expected_price = results["current_spend"]["extraction"]["fields"]["Expected Price"]["value"]
if "$12/month" not in str(current_spend):
    raise SystemExit(f"Monthly Tool Spend is wrong: {current_spend!r}")
if "$39/month" not in str(expected_price):
    raise SystemExit(f"Expected Price is wrong: {expected_price!r}")
if "$39/month" in str(current_spend):
    raise SystemExit("Monthly Tool Spend was contaminated by willingness-to-pay pricing.")

pricing_expected = results["pricing"]["extraction"]["fields"]["Expected Price"]["value"]
pricing_max = results["pricing"]["extraction"]["fields"]["Max Price"]["value"]
if "$29/month" not in str(pricing_expected):
    raise SystemExit(f"Pricing Expected Price is wrong: {pricing_expected!r}")
if "$49/month" not in str(pricing_max):
    raise SystemExit(f"Pricing Max Price is wrong: {pricing_max!r}")

confusion = results["confusion"]["extraction"]["fields"]
if confusion["Did They Understand The Tool Quickly?"]["value"] not in {"Confused", "Very Confused", "Somewhat"}:
    raise SystemExit(f"Understanding signal is wrong: {confusion['Did They Understand The Tool Quickly?']['value']!r}")
if confusion["Did They Use A Prompt?"]["value"] is not True:
    raise SystemExit("Prompt usage was not detected.")
if confusion["Follow-Up Booked?"]["value"] is not True:
    raise SystemExit("Follow-up booking was not detected.")

if not results["current_spend"]["extraction"]["qa_pairs"]:
    raise SystemExit("QA pairs were not produced.")

for name in fixtures:
    if not (output_dir / f"{name}.qa_pairs.json").exists():
        raise SystemExit(f"Missing qa_pairs output for {name}")
    if not (output_dir / f"{name}.field_extraction.json").exists():
        raise SystemExit(f"Missing field_extraction output for {name}")

print("PASS")
PY
