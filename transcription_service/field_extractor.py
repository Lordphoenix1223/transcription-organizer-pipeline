from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from .analysis import HeuristicAnalysis, extract_interview_signals
from .field_question_map import FIELD_SPECS, FieldSpec
from .interview_parser import InterviewQAPair, parse_interview_qa_pairs


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_MONEY_RE = re.compile(
    r"(?<!\w)(?:[$€£]\s?\d[\d,]*(?:\.\d{1,2})?(?:\s?(?:usd|dollars?|bucks|per month|/month|monthly|mo|a month|per year|annual|yearly|annually))?|\d[\d,]*(?:\.\d{1,2})?\s?(?:usd|dollars?|bucks|per month|/month|monthly|mo|a month|per year|annual|yearly|annually))",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"(?<!\w)(\d{1,3}(?:\.\d+)?)\s*%")
_NUMBER_RE = re.compile(r"(?<!\w)(\d+(?:\.\d+)?)")

_CURRENT_SPEND_QUESTION_HINTS = (
    "how much do you spend",
    "how much do you pay",
    "what do you pay",
    "what are you paying",
    "monthly tool spend",
    "what subscriptions do you pay for",
    "how much are your tools",
    "what tools do you currently pay for",
    "currently pay for each month",
    "pay for each month",
    "what do you spend on tools",
)
_PRICE_QUESTION_HINTS = (
    "how much would you pay",
    "what would you pay",
    "what price would you pay",
    "expected price",
    "maximum price",
    "max price",
    "price ceiling",
)
_VIDEO_CHANGE_HINTS = (
    "did the tool change the output",
    "did it change the video",
    "what changed in the video",
)
_UNDERSTANDING_HINTS = (
    "did you understand the tool",
    "did it make sense",
    "was it clear",
    "did you get it",
)


@dataclass(frozen=True)
class FieldExtractionResult:
    value: Any
    confidence: float
    evidence: list[str]
    source_question: Optional[str]
    method: str
    published_to_notion: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "source_question": self.source_question,
            "method": self.method,
            "published_to_notion": self.published_to_notion,
        }


@dataclass(frozen=True)
class InterviewExtraction:
    title: str
    transcript: str
    recording_date: Optional[str]
    qa_pairs: list[dict[str, Any]]
    fields: dict[str, FieldExtractionResult]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "recording_date": self.recording_date,
            "warnings": self.warnings,
            "qa_pairs": self.qa_pairs,
            "fields": {key: value.to_dict() for key, value in self.fields.items()},
        }


def _split_sentences(text: str) -> list[str]:
    return [sentence.strip(" -•\t\r") for sentence in _SENTENCE_SPLIT_RE.split(text) if sentence and sentence.strip(" -•\t\r")]


def _dedupe(values: list[str], limit: Optional[int] = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        result.append(cleaned)
        if limit is not None and len(result) >= limit:
            break
    return result


def _normalize_not_mentioned(values: list[str], fallback: str = "Not mentioned") -> str:
    cleaned = [value.strip() for value in values if value and value.strip()]
    if not cleaned:
        return fallback
    if all(value.lower().startswith("no explicit") or value.lower().startswith("not mentioned") for value in cleaned):
        return fallback
    return "\n".join(cleaned)


def _trim_evidence(text: str, limit: int = 220) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _qa_pairs_to_dicts(qa_pairs: list[InterviewQAPair]) -> list[dict[str, Any]]:
    return [pair.to_dict() for pair in qa_pairs]


def _question_matches(question: str, patterns: tuple[str, ...]) -> bool:
    lower = question.lower()
    return any(pattern in lower for pattern in patterns)


def _best_pair(qa_pairs: list[InterviewQAPair], patterns: tuple[str, ...]) -> Optional[InterviewQAPair]:
    scored: list[tuple[float, InterviewQAPair]] = []
    for pair in qa_pairs:
        question_lower = pair.question.lower()
        answer_lower = pair.answer.lower()
        score = 0.0
        for pattern in patterns:
            if pattern in question_lower:
                score += 2.0
            if pattern in answer_lower:
                score += 0.5
        if score:
            score += min(len(pair.answer) / 200.0, 1.0)
            score += pair.confidence
            scored.append((score, pair))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def _best_snippet(text: str, keywords: tuple[str, ...], limit: int = 2) -> list[str]:
    sentences = _split_sentences(text)
    matches = [sentence for sentence in sentences if any(keyword in sentence.lower() for keyword in keywords)]
    if not matches:
        return []
    return _dedupe(matches, limit=limit)


def _extract_price_mentions(text: str) -> list[str]:
    matches = [match.group(0).strip() for match in _MONEY_RE.finditer(text)]
    cleaned: list[str] = []
    for mention in _dedupe(matches):
        normalized = re.sub(r"\s+", " ", mention)
        normalized = normalized.replace(" per month", "/month")
        normalized = normalized.replace(" monthly", "/month")
        normalized = normalized.replace(" a month", "/month")
        normalized = normalized.replace(" per year", "/year")
        normalized = normalized.replace(" annually", "/year")
        normalized = normalized.replace(" yearly", "/year")
        cleaned.append(normalized)
    return cleaned


def _price_value_from_text(text: str) -> Optional[str]:
    price_mentions = _extract_price_mentions(text)
    if price_mentions:
        return price_mentions[0]
    percent_match = _PERCENT_RE.search(text)
    if percent_match:
        return percent_match.group(0)
    number_match = _NUMBER_RE.search(text)
    if number_match:
        return number_match.group(1)
    return None


def _select_option(value: Optional[str], options: tuple[str, ...]) -> Optional[str]:
    if not value:
        return None
    lower = value.lower()
    for option in options:
        if option.lower() in lower:
            return option
    return None


def _field_result(
    value: Any,
    confidence: float,
    evidence: list[str],
    source_question: Optional[str],
    method: str,
    published_to_notion: bool,
) -> FieldExtractionResult:
    return FieldExtractionResult(
        value=value,
        confidence=round(max(0.0, min(1.0, confidence)), 3),
        evidence=_dedupe(evidence, limit=4),
        source_question=source_question,
        method=method,
        published_to_notion=published_to_notion,
    )


def _infer_checkbox_from_text(text: str, affirmative_keywords: tuple[str, ...], negative_keywords: tuple[str, ...] = ()) -> bool:
    lower = text.lower()
    if any(keyword in lower for keyword in negative_keywords):
        return False
    return any(keyword in lower for keyword in affirmative_keywords)


def _infer_select_from_signals(value: Optional[str], options: tuple[str, ...], fallback: Optional[str] = None) -> Optional[str]:
    if value and value in options:
        return value
    return fallback


def _extract_text_from_pair(pair: Optional[InterviewQAPair], fallback: str = "Not mentioned") -> tuple[str, list[str], float, Optional[str], str]:
    if not pair:
        return fallback, [], 0.0, None, "missing"
    answer = pair.answer.strip()
    if not answer:
        return fallback, [], 0.15, pair.question, "empty_answer"
    return answer, [_trim_evidence(answer)], 0.8 if len(answer) > 20 else 0.6, pair.question, "qa_pair"


def _extract_text_by_question(
    qa_pairs: list[InterviewQAPair],
    patterns: tuple[str, ...],
    keywords: tuple[str, ...] = (),
    fallback: str = "Not mentioned",
) -> tuple[str, list[str], float, Optional[str], str]:
    pair = _best_pair(qa_pairs, patterns)
    if pair is None:
        return fallback, [], 0.0, None, "missing"
    answer = pair.answer.strip()
    if not answer:
        return fallback, [], 0.2, pair.question, "empty_answer"
    evidence = _best_snippet(answer, keywords, limit=2) if keywords else [_trim_evidence(answer)]
    confidence = 0.9 if any(keyword in answer.lower() for keyword in keywords) else 0.75
    return answer, evidence or [_trim_evidence(answer)], confidence, pair.question, "qa_pair"


def _extract_price_by_question(
    qa_pairs: list[InterviewQAPair],
    patterns: tuple[str, ...],
    text: str,
) -> tuple[str, list[str], float, Optional[str], str]:
    pair = _best_pair(qa_pairs, patterns)
    if pair is None:
        return "Not mentioned", [], 0.0, None, "missing"
    answer = pair.answer.strip()
    if not answer:
        return "Not mentioned", [], 0.2, pair.question, "empty_answer"
    price = _price_value_from_text(answer)
    if price is None:
        price = _normalize_not_mentioned(_best_snippet(answer, ("price", "cost", "pay", "subscription", "month"), limit=2))
        if price == "Not mentioned":
            return "Not mentioned", [_trim_evidence(answer)], 0.35, pair.question, "qa_pair_no_price"
        return price, [_trim_evidence(answer)], 0.55, pair.question, "qa_pair_text"
    return price, [_trim_evidence(answer)], 0.95, pair.question, "qa_pair_price"


def _extract_goal_from_text(text: str) -> list[str]:
    lower = text.lower()
    goals = []
    for needle, label in (
        ("views", "Views"),
        ("engagement", "Engagement"),
        ("followers", "Followers"),
        ("brand awareness", "Brand Awareness"),
        ("sales", "Sales"),
        ("client approval", "Client Approval"),
    ):
        if needle in lower:
            goals.append(label)
    return goals


def _extract_platform_from_text(text: str) -> Optional[str]:
    lower = text.lower()
    options = []
    for needle, label in (
        ("tiktok", "TikTok"),
        ("instagram reels", "Instagram Reels"),
        ("youtube shorts", "YouTube Shorts"),
        ("linkedin", "LinkedIn"),
    ):
        if needle in lower:
            options.append(label)
    if len(set(options)) > 1:
        return "Multiple"
    return options[0] if options else None


def _extract_posts_per_week(text: str) -> Optional[float]:
    lower = text.lower()
    patterns = (
        re.search(r"(\d+(?:\.\d+)?)\s+posts?\s+per\s+week", lower),
        re.search(r"(\d+(?:\.\d+)?)\s+times?\s+(?:a|per)\s+week", lower),
        re.search(r"post\s+(\d+(?:\.\d+)?)\s+times?", lower),
    )
    for match in patterns:
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                continue
    return None


def _first_sentence(text: str) -> str:
    sentences = _split_sentences(text)
    return sentences[0] if sentences else text.strip()


def extract_interview_fields(
    transcript: str,
    analysis: HeuristicAnalysis,
    recording_date: Optional[str] = None,
    title: Optional[str] = None,
) -> InterviewExtraction:
    cleaned_transcript = transcript.strip()
    qa_pairs = parse_interview_qa_pairs(cleaned_transcript)
    qa_pair_dicts = _qa_pairs_to_dicts(qa_pairs)
    signals = extract_interview_signals(cleaned_transcript)
    warnings: list[str] = []

    fields: dict[str, FieldExtractionResult] = {}

    def set_text(field_name: str, value: str, evidence: list[str], confidence: float, source_question: Optional[str], method: str, published: bool = True) -> None:
        fields[field_name] = _field_result(value, confidence, evidence, source_question, method, published)

    def set_number(field_name: str, value: Optional[float], evidence: list[str], confidence: float, source_question: Optional[str], method: str, published: bool = True) -> None:
        fields[field_name] = _field_result(value, confidence, evidence, source_question, method, published)

    def set_checkbox(field_name: str, value: bool, evidence: list[str], confidence: float, source_question: Optional[str], method: str, published: bool = True) -> None:
        fields[field_name] = _field_result(value, confidence, evidence, source_question, method, published)

    def set_select(field_name: str, value: Optional[str], evidence: list[str], confidence: float, source_question: Optional[str], method: str, published: bool = True) -> None:
        fields[field_name] = _field_result(value, confidence, evidence, source_question, method, published)

    title_value = title or "Interview"
    set_text("Test Interview", title_value, [title_value], 1.0, None, "title", True)
    set_text("Transcript", cleaned_transcript or "Not mentioned", [_trim_evidence(cleaned_transcript, 400)] if cleaned_transcript else [], 1.0, None, "transcript", True)
    set_text("Analysis", analysis.to_markdown(), [_trim_evidence(analysis.to_markdown(), 400)], 1.0, None, "analysis", True)

    section_map = {
        "Biggest Pain Points": (analysis.biggest_pain_points, "pain_points"),
        "Feature Requests": (analysis.feature_requests, "feature_requests"),
        "Positive Feedback": (analysis.positive_feedback, "positive_feedback"),
        "Pricing Feedback": (analysis.pricing_feedback, "pricing_feedback"),
        "Action Items": (analysis.action_items, "action_items"),
        "Key Quotes": (analysis.exact_quote_candidates, "key_quotes"),
    }
    for field_name, (items, method) in section_map.items():
        value = _normalize_not_mentioned(items)
        confidence = 0.9 if value != "Not mentioned" else 0.0
        evidence = [_trim_evidence(item) for item in items if item and not item.lower().startswith("no explicit") and not item.lower().startswith("no strong")]
        set_text(field_name, value, evidence, confidence, None, method, True)

    set_number("PMF Score", analysis.pmf_score, [str(analysis.pmf_score)], 1.0, None, "analysis", True)
    set_number("Retention Likelihood", analysis.retention_likelihood, [str(analysis.retention_likelihood)], 1.0, None, "analysis", True)
    set_text("Suggested Price", analysis.suggested_price, [analysis.suggested_price], 1.0, None, "analysis", True)
    set_select("Would Pay?", analysis.would_pay if analysis.would_pay in {"Yes", "No"} else None, [analysis.would_pay], 0.95, None, "analysis", True)

    current_tools_value, current_tools_evidence, current_tools_confidence, current_tools_question, current_tools_method = _extract_text_by_question(
        qa_pairs,
        (
            "what tools do you use",
            "what tools are you using",
            "what is your current workflow",
            "what software do you use",
            "what do you use today",
        ),
        ("capcut", "premiere", "final cut", "davinci", "descript", "notion", "canva", "google docs", "sheets", "docs"),
    )
    set_text("Current Tools", current_tools_value, current_tools_evidence, current_tools_confidence, current_tools_question, current_tools_method, True)

    spend_value, spend_evidence, spend_confidence, spend_question, spend_method = _extract_price_by_question(
        qa_pairs,
        _CURRENT_SPEND_QUESTION_HINTS,
        cleaned_transcript,
    )
    if spend_value == "Not mentioned":
        spend_evidence = []
    set_text("Monthly Tool Spend", spend_value, spend_evidence, spend_confidence, spend_question, spend_method, True)

    platform_value = signals.get("platform") or _extract_platform_from_text(cleaned_transcript)
    set_select("Platform", platform_value if platform_value in {"TikTok", "Instagram Reels", "YouTube Shorts", "LinkedIn", "Multiple"} else None, [platform_value] if platform_value else [], 0.8 if platform_value else 0.0, None, "signals", True)

    posts_per_week = _extract_posts_per_week(cleaned_transcript)
    set_number("Posts Per Week", posts_per_week, [str(posts_per_week)] if posts_per_week is not None else [], 0.85 if posts_per_week is not None else 0.0, None, "signals", True)

    goal_value = signals.get("goal_of_video") or _extract_goal_from_text(cleaned_transcript)
    if not isinstance(goal_value, list):
        goal_value = list(goal_value) if goal_value else []
    goal_value = [item for item in goal_value if item in {"Views", "Engagement", "Followers", "Brand Awareness", "Sales", "Client Approval"}]
    fields["Goal Of Video"] = _field_result(goal_value, 0.78 if goal_value else 0.0, goal_value, None, "signals", True)

    review_value, review_evidence, review_confidence, review_question, review_method = _extract_text_by_question(
        qa_pairs,
        ("what is your review process", "how do you review", "how do you check", "what happens before posting", "what is your approval process"),
        ("review", "approve", "approval", "check", "feedback"),
    )
    set_text("Current Review Process", review_value, review_evidence, review_confidence, review_question, review_method, True)

    uncertainty_value, uncertainty_evidence, uncertainty_confidence, uncertainty_question, uncertainty_method = _extract_text_by_question(
        qa_pairs,
        ("what are you unsure about", "what is your biggest uncertainty", "what worries you", "what are you uncertain about", "what do you not know"),
        ("uncertain", "uncertainty", "unsure", "worried", "confused", "lost"),
    )
    set_text("Biggest Uncertainty", uncertainty_value, uncertainty_evidence, uncertainty_confidence, uncertainty_question, uncertainty_method, True)

    most_value, most_evidence, most_confidence, most_question, most_method = _extract_text_by_question(
        qa_pairs,
        ("what was most valuable", "what was most useful", "what was most helpful", "what did you like most", "what helped you most"),
        ("valuable", "useful", "helpful", "good", "great"),
    )
    set_text("Most Valuable Output", most_value, most_evidence, most_confidence, most_question, most_method, True)

    least_value, least_evidence, least_confidence, least_question, least_method = _extract_text_by_question(
        qa_pairs,
        ("what was least valuable", "what was least useful", "what did you not use", "what was the least helpful", "what felt like a waste"),
        ("least", "waste", "did not use", "didn't use", "unused"),
    )
    set_text("Least Valuable Output", least_value, least_evidence, least_confidence, least_question, least_method, True)

    changed_value, changed_evidence, changed_confidence, changed_question, changed_method = _extract_text_by_question(
        qa_pairs,
        ("what changed", "what was different", "what improved", "after using the tool", "before and after"),
        ("changed", "better", "worse", "different", "improved"),
    )
    set_text("What Changed?", changed_value, changed_evidence, changed_confidence, changed_question, changed_method, True)

    use_next_value = signals.get("posting_intent")
    if use_next_value not in {"Definitely", "Probably", "Maybe", "Unlikely", "No"}:
        use_next_value = None
    set_select("Would Use On Next Video?", use_next_value, [str(use_next_value)] if use_next_value else [], 0.75 if use_next_value else 0.0, None, "signals", True)

    change_value = None
    if signals.get("did_change_video"):
        lower = cleaned_transcript.lower()
        if "major changes" in lower or "completely changed" in lower or "dramatically" in lower:
            change_value = "Yes - Major Changes"
        elif "minor changes" in lower or "slightly changed" in lower or "small changes" in lower:
            change_value = "Yes - Minor Changes"
        elif "confidence only" in lower or "gave confidence" in lower:
            change_value = "Gave Confidence Only"
        elif "no changes" in lower or "didn't change" in lower or "did not change" in lower:
            change_value = "No Changes"
    set_select("Did The Tool Change The Output?", change_value, [change_value] if change_value else [], 0.7 if change_value else 0.0, None, "signals", True)

    understanding_value = signals.get("understanding")
    if understanding_value not in {"Yes", "Mostly", "Somewhat", "Confused", "Very Confused"}:
        understanding_value = None
    set_select("Did They Understand The Tool Quickly?", understanding_value, [str(understanding_value)] if understanding_value else [], 0.7 if understanding_value else 0.0, None, "signals", True)

    confused_snippets = _best_snippet(cleaned_transcript, ("confusing", "unclear", "confused", "lost", "not sure"), limit=3)
    set_text("Where Did They Get Confused?", _normalize_not_mentioned(confused_snippets), confused_snippets, 0.85 if confused_snippets else 0.0, None, "transcript_scan", True)

    onboarding_value = _infer_checkbox_from_text(cleaned_transcript, ("onboarding", "walkthrough", "signed up", "sign up", "setup", "completed setup"), ("didn't", "did not"))
    set_checkbox("Did They Complete Onboarding?", onboarding_value, [_trim_evidence("onboarding signal")] if onboarding_value else [], 0.8 if onboarding_value else 0.35, None, "signals", True)

    create_video_value = _infer_checkbox_from_text(cleaned_transcript, ("created a video", "made a video", "posted a video", "uploaded a video", "make a video"), ("didn't", "did not", "never"))
    set_checkbox("Did They Create A Video?", create_video_value, [_trim_evidence("video creation signal")] if create_video_value else [], 0.8 if create_video_value else 0.35, None, "signals", True)

    prompt_value = _infer_checkbox_from_text(cleaned_transcript, ("prompt", "prompts", "script", "template", "ai prompt"), ("no prompt", "without a prompt", "didn't use a prompt"))
    set_checkbox("Did They Use A Prompt?", prompt_value, [_trim_evidence("prompt signal")] if prompt_value else [], 0.75 if prompt_value else 0.3, None, "signals", True)

    expected_value, expected_evidence, expected_confidence, expected_question, expected_method = _extract_price_by_question(
        qa_pairs,
        _PRICE_QUESTION_HINTS,
        cleaned_transcript,
    )
    set_text("Expected Price", expected_value, expected_evidence, expected_confidence, expected_question, expected_method, True)

    max_question_pair = _best_pair(
        qa_pairs,
        ("what is the maximum price", "what is the most you would pay", "what is your price ceiling", "how much at most", "max price"),
    )
    max_value = "Not mentioned"
    max_evidence: list[str] = []
    max_confidence = 0.0
    max_question = None
    max_method = "missing"
    if max_question_pair:
        max_value = _price_value_from_text(max_question_pair.answer) or _normalize_not_mentioned(_best_snippet(max_question_pair.answer, ("maximum", "max", "ceiling", "at most", "up to"), limit=2))
        max_evidence = [_trim_evidence(max_question_pair.answer)] if max_question_pair.answer else []
        max_confidence = 0.9 if max_value != "Not mentioned" else 0.35
        max_question = max_question_pair.question
        max_method = "qa_pair"
    set_text("Max Price", max_value, max_evidence, max_confidence, max_question, max_method, True)

    referral_value = _infer_checkbox_from_text(cleaned_transcript, ("referral", "refer", "introduce", "connect you", "put you in touch"), ("no referral", "not referral"))
    set_checkbox("Referral Offered?", referral_value, [_trim_evidence("referral signal")] if referral_value else [], 0.65 if referral_value else 0.3, None, "signals", True)

    follow_up_value = _infer_checkbox_from_text(cleaned_transcript, ("follow up", "follow-up", "book", "schedule", "next step", "check in"), ("no follow up", "don't follow up", "do not follow up"))
    set_checkbox("Follow-Up Booked?", follow_up_value, [_trim_evidence("follow-up signal")] if follow_up_value else [], 0.65 if follow_up_value else 0.3, None, "signals", True)

    follow_up_actions_value = _normalize_not_mentioned(analysis.action_items)
    set_text("Follow-Up Actions", follow_up_actions_value, [_trim_evidence(item) for item in analysis.action_items if item and not item.lower().startswith("no clear")], 0.88 if follow_up_actions_value != "Not mentioned" else 0.0, None, "analysis", True)

    user_type_value = None
    user_type_text = cleaned_transcript.lower()
    if any(keyword in user_type_text for keyword in ("startup", "creator", "i make content", "i post content", "youtube", "tiktok", "instagram")):
        user_type_value = "Creator"
    elif any(keyword in user_type_text for keyword in ("agency", "client", "clients")):
        user_type_value = "Agency"
    elif any(keyword in user_type_text for keyword in ("brand", "marketing team", "marketing")):
        user_type_value = "Brand"
    elif any(keyword in user_type_text for keyword in ("editor", "edit")):
        user_type_value = "Editor"
    set_select("User Type", user_type_value, [user_type_value] if user_type_value else [], 0.45 if user_type_value else 0.0, None, "signals", True)

    video_used_value = None
    video_pair = _best_pair(qa_pairs, ("what video did you use", "which video did you use", "what content did you use", "what was the video"))
    if video_pair and video_pair.answer.strip():
        video_used_value = video_pair.answer.strip()
    elif cleaned_transcript:
        for keyword in ("youtube", "instagram", "tiktok", "linkedin", "capcut", "cursorful"):
            if keyword in cleaned_transcript.lower():
                video_used_value = _first_sentence(cleaned_transcript)
                break
    set_text("Video Used", video_used_value or "Not mentioned", [_trim_evidence(video_used_value)] if video_used_value else [], 0.5 if video_used_value else 0.0, video_pair.question if video_pair else None, "qa_pair" if video_pair else "missing", True)

    pain_score = min(10, max(1, 5 + len(analysis.biggest_pain_points) - len(analysis.positive_feedback)))
    disappointment_score = min(10, max(1, 5 + len(analysis.negative_confusing_feedback) - len(analysis.positive_feedback)))
    set_number("Pain Score", pain_score, [str(pain_score)], 0.8, None, "analysis", True)
    set_number("Disappointment Score", disappointment_score, [str(disappointment_score)], 0.8, None, "analysis", True)

    if signals.get("platform") and not platform_value:
        warnings.append("Platform inferred from transcript signals rather than a direct answer.")

    if any("No explicit" in item for item in analysis.biggest_pain_points + analysis.feature_requests + analysis.positive_feedback):
        warnings.append("Some analysis sections did not produce explicit evidence and were filled conservatively.")

    def _needs_review(result: FieldExtractionResult) -> bool:
        if result.confidence >= 0.5:
            return False
        if result.value is None:
            return False
        if result.value == "Not mentioned":
            return False
        if result.value is False:
            return False
        if isinstance(result.value, list) and not result.value:
            return False
        return True

    if any(_needs_review(result) for result in fields.values()):
        warnings.append("Some extracted fields have low confidence and should be reviewed.")

    return InterviewExtraction(
        title=title_value,
        transcript=cleaned_transcript,
        recording_date=recording_date,
        qa_pairs=qa_pair_dicts,
        fields=fields,
        warnings=warnings,
    )
