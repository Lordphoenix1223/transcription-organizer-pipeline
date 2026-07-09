from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .analysis import HeuristicAnalysis
from .field_extractor import InterviewExtraction, extract_interview_fields

if TYPE_CHECKING:
    from notion_client import Client


SUPPORTED_NOTION_TYPES = {
    "title",
    "rich_text",
    "text",
    "number",
    "select",
    "multi_select",
    "checkbox",
    "date",
    "status",
    "url",
    "email",
    "phone_number",
}


@dataclass(frozen=True)
class NotionPropertySchema:
    name: str
    type: str
    options: tuple[str, ...] = ()
    raw: dict[str, Any] | None = None


def _cached_beta_interview_schema() -> dict[str, NotionPropertySchema]:
    return {
        "Action Items": NotionPropertySchema("Action Items", "text"),
        "Analysis": NotionPropertySchema("Analysis", "text"),
        "Biggest Pain Points": NotionPropertySchema("Biggest Pain Points", "text"),
        "Biggest Uncertainty": NotionPropertySchema("Biggest Uncertainty", "text"),
        "Current Review Process": NotionPropertySchema("Current Review Process", "text"),
        "Current Tools": NotionPropertySchema("Current Tools", "text"),
        "Did The Tool Change The Output?": NotionPropertySchema(
            "Did The Tool Change The Output?",
            "select",
            options=("Yes - Major Changes", "Yes - Minor Changes", "No Changes", "Gave Confidence Only"),
        ),
        "Did They Complete Onboarding?": NotionPropertySchema("Did They Complete Onboarding?", "checkbox"),
        "Did They Create A Video?": NotionPropertySchema("Did They Create A Video?", "checkbox"),
        "Did They Understand The Tool Quickly?": NotionPropertySchema(
            "Did They Understand The Tool Quickly?",
            "select",
            options=("Yes", "Mostly", "Somewhat", "Confused", "Very Confused"),
        ),
        "Did They Use A Prompt?": NotionPropertySchema("Did They Use A Prompt?", "checkbox"),
        "Disappointment Score": NotionPropertySchema("Disappointment Score", "number"),
        "Expected Price": NotionPropertySchema("Expected Price", "text"),
        "Feature Requests": NotionPropertySchema("Feature Requests", "text"),
        "Follow-Up Actions": NotionPropertySchema("Follow-Up Actions", "text"),
        "Follow-Up Booked?": NotionPropertySchema("Follow-Up Booked?", "checkbox"),
        "Goal Of Video": NotionPropertySchema(
            "Goal Of Video",
            "multi_select",
            options=("Views", "Engagement", "Followers", "Brand Awareness", "Sales", "Client Approval"),
        ),
        "Interview Date": NotionPropertySchema("Interview Date", "date"),
        "Key Quotes": NotionPropertySchema("Key Quotes", "text"),
        "Least Valuable Output": NotionPropertySchema("Least Valuable Output", "text"),
        "Max Price": NotionPropertySchema("Max Price", "text"),
        "Monthly Tool Spend": NotionPropertySchema("Monthly Tool Spend", "text"),
        "Most Valuable Output": NotionPropertySchema("Most Valuable Output", "text"),
        "PMF Score": NotionPropertySchema("PMF Score", "number"),
        "Pain Score": NotionPropertySchema("Pain Score", "number"),
        "Participant Name": NotionPropertySchema("Participant Name", "text"),
        "Platform": NotionPropertySchema(
            "Platform",
            "select",
            options=("TikTok", "Instagram Reels", "YouTube Shorts", "LinkedIn", "Multiple"),
        ),
        "Positive Feedback": NotionPropertySchema("Positive Feedback", "text"),
        "Posts Per Week": NotionPropertySchema("Posts Per Week", "number"),
        "Pricing Feedback": NotionPropertySchema("Pricing Feedback", "text"),
        "Referral Offered?": NotionPropertySchema("Referral Offered?", "checkbox"),
        "Retention Likelihood": NotionPropertySchema("Retention Likelihood", "number"),
        "Status": NotionPropertySchema(
            "Status",
            "status",
            options=("Completed", "Analyzed", "Needs Follow-up", "Scheduled"),
        ),
        "Suggested Price": NotionPropertySchema("Suggested Price", "text"),
        "Test Interview": NotionPropertySchema("Test Interview", "title"),
        "Transcript": NotionPropertySchema("Transcript", "text"),
        "User Type": NotionPropertySchema(
            "User Type",
            "select",
            options=("Creator", "Agency", "Brand", "Editor", "Marketing Team"),
        ),
        "Video Used": NotionPropertySchema("Video Used", "text"),
        "What Changed?": NotionPropertySchema("What Changed?", "text"),
        "Where Did They Get Confused?": NotionPropertySchema("Where Did They Get Confused?", "text"),
        "Would Pay?": NotionPropertySchema("Would Pay?", "select", options=("Yes", "No")),
        "Would Use On Next Video?": NotionPropertySchema(
            "Would Use On Next Video?",
            "select",
            options=("Definitely", "Probably", "Maybe", "Unlikely", "No"),
        ),
    }


def _rich_text_item(content: str) -> dict[str, Any]:
    return {"text": {"content": content}}


def _rich_text_content(text: str, chunk_size: int = 1800) -> list[dict[str, Any]]:
    cleaned = (text or "").strip()
    if not cleaned:
        return [_rich_text_item("Not mentioned")]
    return [_rich_text_item(cleaned[i : i + chunk_size]) for i in range(0, len(cleaned), chunk_size)]


def _normalize_text(value: Any, fallback: str = "Not mentioned") -> str:
    if value is None:
        return fallback
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or fallback
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(cleaned) if cleaned else fallback
    return str(value)


def _extract_date(recording_date: Optional[str]) -> Optional[str]:
    if not recording_date:
        return None
    try:
        return datetime.fromisoformat(recording_date).date().isoformat()
    except Exception:
        return None


def _coerce_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _coerce_checkbox(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1"}:
            return True
        if lowered in {"false", "no", "n", "0"}:
            return False
    return None


def _coerce_select_name(value: Any, options: tuple[str, ...]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned == "Not mentioned":
            return None
        if options and cleaned not in options:
            return None
        return cleaned
    if isinstance(value, (int, float, bool)):
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned == "Not mentioned":
        return None
    if options and cleaned not in options:
        return None
    return cleaned


def _coerce_multi_select(values: Any, options: tuple[str, ...]) -> Optional[list[dict[str, str]]]:
    if values is None:
        return None
    if isinstance(values, str):
        items = [item.strip() for item in values.split("\n") if item.strip() and item.strip() != "Not mentioned"]
    else:
        items = [str(item).strip() for item in values if str(item).strip() and str(item).strip() != "Not mentioned"]
    if not items:
        return None
    if options:
        items = [item for item in items if item in options]
    if not items:
        return None
    return [{"name": item} for item in items]


def _coerce_scalar_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return "\n".join(cleaned) if cleaned else None
    return str(value)


def _clean_title_candidate(value: Any) -> Optional[str]:
    text = _coerce_scalar_text(value)
    if text is None:
        return None
    candidate = text.strip()
    if not candidate or candidate == "Not mentioned":
        return None
    return Path(candidate).stem or candidate


def _timestamp_title() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def _coerce_title(value: Any, fallback: str | None = None) -> Optional[list[dict[str, Any]]]:
    title = _clean_title_candidate(value)
    if title is None and fallback is not None:
        title = _clean_title_candidate(fallback)
    if title is None:
        title = f"Untitled Interview {_timestamp_title()}"
    return [_rich_text_item(title)]


def resolve_interview_title(
    title: Any = None,
    *,
    transcript_bundle_name: Any = None,
    transcript_metadata: Optional[dict[str, Any]] = None,
    fallback_timestamp: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> str:
    resolved = _clean_title_candidate(title)
    if resolved is None:
        resolved = _clean_title_candidate(transcript_bundle_name)
    if resolved is None and transcript_metadata:
        resolved = _clean_title_candidate(transcript_metadata.get("original_filename"))
    if resolved is None:
        timestamp = _clean_title_candidate(fallback_timestamp) if fallback_timestamp else None
        resolved = f"Untitled Interview {timestamp or _timestamp_title()}"
    if logger is not None:
        logger.info("Resolved title: %s", resolved)
    return resolved


def _extract_field_value(
    extraction: InterviewExtraction,
    field_name: str,
    resolved_title: str,
    transcript: str,
    analysis: HeuristicAnalysis,
    recording_date: Optional[str],
    participant_name: Optional[str],
) -> Any:
    if field_name == "Test Interview":
        return resolved_title
    if field_name == "Transcript":
        return transcript
    if field_name == "Analysis":
        return analysis.to_markdown()
    if field_name == "Interview Date":
        return _extract_date(recording_date)
    if field_name == "Participant Name":
        if participant_name:
            return participant_name
    if field_name == "Status":
        return "Analyzed"

    field = extraction.fields.get(field_name)
    if field is None:
        return None
    return field.value


def load_notion_database_schema(client: Client, database_id: str) -> dict[str, NotionPropertySchema]:
    try:
        database = client.databases.retrieve(database_id=database_id)
        raw_properties = database.get("properties") or {}
    except Exception:
        raw_properties = {}
    schema: dict[str, NotionPropertySchema] = {}

    for name, spec in raw_properties.items():
        notion_type = spec.get("type")
        options: tuple[str, ...] = ()
        if notion_type == "select":
            options = tuple(option.get("name", "") for option in spec.get("select", {}).get("options", []) if option.get("name"))
        elif notion_type == "multi_select":
            options = tuple(option.get("name", "") for option in spec.get("multi_select", {}).get("options", []) if option.get("name"))
        elif notion_type == "status":
            status_spec = spec.get("status", {})
            status_options = status_spec.get("options", []) or []
            if status_options:
                options = tuple(option.get("name", "") for option in status_options if option.get("name"))
            else:
                groups = status_spec.get("groups", {}) or {}
                flattened: list[str] = []
                for group in groups.values():
                    for option in group or []:
                        if option.get("name"):
                            flattened.append(option["name"])
                options = tuple(flattened)
        schema[name] = NotionPropertySchema(name=name, type=notion_type, options=options, raw=spec)
    if not schema:
        return _cached_beta_interview_schema()
    return schema


def print_notion_schema(schema: dict[str, NotionPropertySchema]) -> str:
    lines = []
    for name in sorted(schema):
        spec = schema[name]
        if spec.options:
            lines.append(f"{name}: {spec.type} [{', '.join(spec.options)}]")
        else:
            lines.append(f"{name}: {spec.type}")
    return "\n".join(lines)


def format_notion_property(
    field_name: str,
    schema: NotionPropertySchema,
    value: Any,
) -> tuple[Optional[dict[str, Any]], str]:
    notion_type = schema.type

    if notion_type not in SUPPORTED_NOTION_TYPES:
        return None, f"Skipped {field_name} because Notion property type was {notion_type}"

    if notion_type == "title":
        payload = _coerce_title(value, fallback=None)
        return {"title": payload}, "published"

    if notion_type in {"rich_text", "text"}:
        text = _coerce_scalar_text(value)
        if text is None:
            return None, f"Skipped {field_name} because value was empty"
        return {"rich_text": _rich_text_content(text)}, "published"

    if notion_type == "number":
        number = _coerce_float(value)
        if number is None:
            return None, f"Skipped {field_name} because value was empty"
        return {"number": number}, "published"

    if notion_type == "checkbox":
        checkbox = _coerce_checkbox(value)
        if checkbox is None:
            return None, f"Skipped {field_name} because value was empty"
        return {"checkbox": checkbox}, "published"

    if notion_type == "select":
        select_name = _coerce_select_name(value, schema.options)
        if select_name is None:
            return None, f"Skipped {field_name} because value was empty"
        return {"select": {"name": select_name}}, "published"

    if notion_type == "status":
        status_name = _coerce_select_name(value, schema.options)
        if status_name is None:
            return None, f"Skipped {field_name} because value was empty"
        return {"status": {"name": status_name}}, "published"

    if notion_type == "multi_select":
        items = _coerce_multi_select(value, schema.options)
        if items is None:
            return None, f"Skipped {field_name} because value was empty"
        return {"multi_select": items}, "published"

    if notion_type in {"url", "email", "phone_number"}:
        text = _coerce_scalar_text(value)
        if text is None:
            return None, f"Skipped {field_name} because value was empty"
        return {notion_type: text}, "published"

    if notion_type == "date":
        text = _coerce_scalar_text(value)
        if text is None:
            return None, f"Skipped {field_name} because value was empty"
        return {"date": {"start": text}}, "published"

    return None, f"Skipped {field_name} because Notion property type was {notion_type}"


def build_notion_properties(
    title: str,
    transcript: str,
    analysis: HeuristicAnalysis,
    recording_date: Optional[str] = None,
    participant_name: Optional[str] = None,
    extraction: Optional[InterviewExtraction] = None,
    schema: Optional[dict[str, NotionPropertySchema]] = None,
    logger: Optional[logging.Logger] = None,
    transcript_bundle_name: Any = None,
    transcript_metadata: Optional[dict[str, Any]] = None,
    fallback_timestamp: Optional[str] = None,
) -> dict[str, Any]:
    resolved_title = resolve_interview_title(
        title,
        transcript_bundle_name=transcript_bundle_name,
        transcript_metadata=transcript_metadata,
        fallback_timestamp=fallback_timestamp,
        logger=logger,
    )
    if extraction is None:
        extraction = extract_interview_fields(
            transcript=transcript,
            analysis=analysis,
            recording_date=recording_date,
            title=resolved_title,
        )
    if schema is None:
        raise ValueError("Notion schema is required before publishing.")

    properties: dict[str, Any] = {}
    for field_name, schema_spec in schema.items():
        raw_value = _extract_field_value(
            extraction=extraction,
            field_name=field_name,
            resolved_title=resolved_title,
            transcript=transcript,
            analysis=analysis,
            recording_date=recording_date,
            participant_name=participant_name,
        )
        payload, message = format_notion_property(field_name, schema_spec, raw_value)

        if payload is None:
            if logger is not None:
                logger.info(message)
            continue

        properties[field_name] = payload
        if logger is not None:
            logger.info("Published %s | type=%s | value=%r", field_name, schema_spec.type, raw_value)

    if "Would Pay?" in schema and "Would Pay?" not in properties and logger is not None:
        logger.info("Skipped Would Pay? because Notion property type was %s", schema["Would Pay?"].type)

    return properties
