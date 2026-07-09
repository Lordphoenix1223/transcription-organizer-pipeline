from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from .interview_parser import parse_interview_qa_pairs


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_QUOTE_RE = re.compile(r'["“”](.+?)["“”]|[\'‘’](.+?)[\'‘’]')
_PRICE_RE = re.compile(
    r"(?<!\w)(?:[$€£]\s?\d[\d,]*(?:\.\d{1,2})?(?:\s?(?:usd|dollars?|bucks|per month|/month|monthly|mo|a month|per year|annual|yearly|annually))?|\d[\d,]*(?:\.\d{1,2})?\s?(?:usd|dollars?|bucks|per month|/month|monthly|mo|a month|per year|annual|yearly|annually))",
    re.IGNORECASE,
)

_PAIN_KEYWORDS = (
    "confusing",
    "unclear",
    "confused",
    "frustrat",
    "pain",
    "slow",
    "hard",
    "stuck",
    "time-consuming",
    "time consuming",
    "missing",
    "bug",
    "broken",
    "problem",
    "issue",
    "manual",
    "awkward",
    "difficult",
    "clunky",
    "annoying",
    "can't",
    "cannot",
    "doesn't work",
    "dont work",
    "don't work",
)
_FEATURE_REQUEST_KEYWORDS = (
    "i wish",
    "it should",
    "can it",
    "would be better",
    "needs to",
    "make it",
    "make this",
    "could you",
    "can you",
    "should",
    "need",
    "wish",
    "would like",
    "request",
    "feature",
    "add ",
    "include",
    "improve",
    "support",
    "export",
    "search",
    "filter",
    "if it had",
    "it would be better if",
)
_POSITIVE_KEYWORDS = (
    "love",
    "great",
    "helpful",
    "useful",
    "valuable",
    "clear",
    "easy",
    "nice",
    "cool",
    "awesome",
    "good",
    "like",
    "works well",
    "fast",
    "smooth",
    "thank you",
    "impressed",
)
_NEGATIVE_OR_CONFUSING_KEYWORDS = (
    "i don't get",
    "i do not get",
    "what does this mean",
    "confusing",
    "unclear",
    "not sure",
    "don't understand",
    "dont understand",
    "lost",
    "frustrat",
    "slow",
    "annoying",
    "awkward",
    "hard",
    "too much",
    "too many",
    "price",
    "cost",
    "expensive",
)
_ACTION_ITEM_KEYWORDS = (
    "follow up",
    "follow-up",
    "book",
    "schedule",
    "connect",
    "reach out",
    "next step",
    "let's",
    "let us",
    "we should",
    "i'll",
    "i will",
    "send",
    "fix",
    "check",
    "review",
    "try",
    "test",
    "build",
    "update",
    "share",
)
_WILLING_TO_PAY_KEYWORDS = (
    "would pay",
    "pay for",
    "pay",
    "price",
    "cost",
    "dollar",
    "free",
    "subscription",
    "per month",
    "worth it",
    "subscribe",
    "buy",
    "pricing is fine",
    "reasonable price",
    "good value",
)
_NOT_WILLING_TO_PAY_KEYWORDS = (
    "too expensive",
    "can't pay",
    "cannot pay",
    "wouldn't pay",
    "would not pay",
    "not worth",
    "overpriced",
    "too much",
)


def _split_sentences(text: str) -> list[str]:
    raw_sentences = _SENTENCE_SPLIT_RE.split(text)
    return [sentence.strip(" -•\t\r") for sentence in raw_sentences if sentence and sentence.strip(" -•\t\r")]


def _dedupe(values: Iterable[str], limit: Optional[int] = None) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if limit is not None and len(result) >= limit:
            break
    return result


def _pick_sentences(sentences: Iterable[str], keywords: tuple[str, ...], limit: int = 5) -> list[str]:
    matches = [sentence for sentence in sentences if any(keyword in sentence.lower() for keyword in keywords)]
    return _dedupe(matches, limit=limit)


def _extract_price_mentions(transcript: str) -> list[str]:
    matches = _dedupe(match.group(0).strip() for match in _PRICE_RE.finditer(transcript))
    normalized: list[str] = []
    for mention in matches:
        cleaned = re.sub(r"\s+", " ", mention)
        cleaned = cleaned.replace(" per month", "/month")
        cleaned = cleaned.replace(" monthly", "/month")
        cleaned = cleaned.replace(" a month", "/month")
        cleaned = cleaned.replace(" per year", "/year")
        cleaned = cleaned.replace(" annually", "/year")
        cleaned = cleaned.replace(" yearly", "/year")
        normalized.append(cleaned)
    return normalized


def _score_word_hits(text: str, keywords: tuple[str, ...]) -> int:
    lower = text.lower()
    return sum(lower.count(keyword) for keyword in keywords)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in keywords)


def _quote_candidates(transcript: str, sentences: list[str]) -> list[str]:
    candidates: list[str] = []

    for match in _QUOTE_RE.finditer(transcript):
        quoted = match.group(1) or match.group(2)
        if quoted and len(quoted.strip()) >= 4:
            candidates.append(quoted.strip())

    for sentence in sentences:
        lower = sentence.lower()
        if any(marker in lower for marker in ("i ", "we ", "they ", "it ", "this ", "that ")):
            if _contains_any(sentence, _POSITIVE_KEYWORDS + _NEGATIVE_OR_CONFUSING_KEYWORDS + _FEATURE_REQUEST_KEYWORDS + _PAIN_KEYWORDS):
                candidates.append(sentence)

    return _dedupe(candidates, limit=8)


def _would_pay(transcript: str, pricing_feedback: list[str], positive_feedback: list[str], negative_feedback: list[str]) -> str:
    lower = transcript.lower()
    positive_signal = _contains_any(lower, _WILLING_TO_PAY_KEYWORDS)
    negative_signal = _contains_any(lower, _NOT_WILLING_TO_PAY_KEYWORDS)

    if positive_signal and not negative_signal:
        return "Yes"
    if negative_signal and not positive_signal:
        return "No"

    pricing_text = " ".join(pricing_feedback).lower()
    if _contains_any(pricing_text, _WILLING_TO_PAY_KEYWORDS) and not _contains_any(pricing_text, _NOT_WILLING_TO_PAY_KEYWORDS):
        return "Yes"
    if _contains_any(pricing_text, _NOT_WILLING_TO_PAY_KEYWORDS):
        return "No"

    if len(positive_feedback) > len(negative_feedback):
        return "Yes"
    return "No"


def _suggested_price(pricing_mentions: list[str], would_pay: str, retention_likelihood: int, pmf_score: int) -> str:
    actual_mentions = [mention for mention in pricing_mentions if mention != "No explicit pricing mention detected"]
    if actual_mentions:
        for mention in actual_mentions:
            extracted_mentions = _extract_price_mentions(mention)
            if extracted_mentions:
                return extracted_mentions[0]
        return actual_mentions[0]
    if would_pay != "Yes":
        return "$0-$15/month"
    if pmf_score >= 8 or retention_likelihood >= 8:
        return "$20-$30/month"
    if pmf_score >= 6:
        return "$15-$20/month"
    return "$10-$15/month"


def _clamp_score(value: int) -> int:
    return max(1, min(10, value))


@dataclass(frozen=True)
class HeuristicAnalysis:
    biggest_pain_points: list[str]
    feature_requests: list[str]
    pricing_mentions: list[str]
    positive_feedback: list[str]
    negative_confusing_feedback: list[str]
    action_items: list[str]
    exact_quote_candidates: list[str]
    pricing_feedback: list[str]
    would_pay: str
    suggested_price: str
    retention_likelihood: int
    pmf_score: int

    @property
    def analysis_label(self) -> str:
        return "heuristic analysis"

    def to_dict(self) -> dict[str, object]:
        return {
            "analysis_label": self.analysis_label,
            "biggest_pain_points": self.biggest_pain_points,
            "feature_requests": self.feature_requests,
            "pricing_mentions": self.pricing_mentions,
            "positive_feedback": self.positive_feedback,
            "negative_confusing_feedback": self.negative_confusing_feedback,
            "action_items": self.action_items,
            "exact_quote_candidates": self.exact_quote_candidates,
            "pricing_feedback": self.pricing_feedback,
            "would_pay": self.would_pay,
            "suggested_price": self.suggested_price,
            "retention_likelihood": self.retention_likelihood,
            "pmf_score": self.pmf_score,
        }

    def _format_section(self, title: str, items: list[str]) -> list[str]:
        lines = [f"## {title}"]
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append("- None found")
        lines.append("")
        return lines

    def to_markdown(self) -> str:
        lines = [
            "# Heuristic analysis",
            "",
            "Deterministic local logic only. No paid LLM APIs were used.",
            "",
            f"- Would Pay?: {self.would_pay}",
            f"- Suggested Price: {self.suggested_price}",
            f"- Retention Likelihood: {self.retention_likelihood}/10",
            f"- PMF Score: {self.pmf_score}/10",
            "",
        ]
        lines.extend(self._format_section("Biggest Pain Points", self.biggest_pain_points))
        lines.extend(self._format_section("Feature Requests", self.feature_requests))
        lines.extend(self._format_section("Pricing Mentions", self.pricing_mentions))
        lines.extend(self._format_section("Pricing Feedback", self.pricing_feedback))
        lines.extend(self._format_section("Positive Feedback", self.positive_feedback))
        lines.extend(self._format_section("Negative / Confusing Feedback", self.negative_confusing_feedback))
        lines.extend(self._format_section("Action Items", self.action_items))
        lines.extend(self._format_section("Exact Quote Candidates", self.exact_quote_candidates))
        return "\n".join(lines).strip()


def analyze_transcript(transcript: str, logger: Optional[logging.Logger] = None) -> HeuristicAnalysis:
    cleaned_transcript = transcript.strip()
    if not cleaned_transcript:
        raise ValueError("Transcript is empty.")

    qa_pairs = parse_interview_qa_pairs(cleaned_transcript)
    answer_only_text = "\n".join(pair.answer for pair in qa_pairs if pair.answer.strip()).strip()
    analysis_source = answer_only_text if len(answer_only_text) >= max(120, len(cleaned_transcript) // 3) else cleaned_transcript

    sentences = _split_sentences(analysis_source)
    lower = analysis_source.lower()

    biggest_pain_points = _pick_sentences(sentences, _PAIN_KEYWORDS, limit=5)
    negative_confusing_feedback = _pick_sentences(sentences, _NEGATIVE_OR_CONFUSING_KEYWORDS, limit=5)
    feature_requests = _pick_sentences(sentences, _FEATURE_REQUEST_KEYWORDS, limit=5)
    positive_feedback = _pick_sentences(sentences, _POSITIVE_KEYWORDS, limit=5)
    pricing_mentions = _dedupe(
        _pick_sentences(sentences, ("price", "cost", "pay", "monthly", "month", "subscription", "plan", "value", "$"), limit=5)
        + _extract_price_mentions(cleaned_transcript),
        limit=8,
    )
    pricing_feedback = _dedupe(pricing_mentions + _pick_sentences(sentences, _WILLING_TO_PAY_KEYWORDS + _NOT_WILLING_TO_PAY_KEYWORDS, limit=5), limit=8)
    exact_quote_candidates = _quote_candidates(cleaned_transcript, sentences)

    if not biggest_pain_points:
        biggest_pain_points = ["No strong pain points detected"]
    if not negative_confusing_feedback:
        negative_confusing_feedback = ["No explicit negative or confusing feedback detected"]
    if not feature_requests:
        feature_requests = ["No explicit feature requests detected"]
    if not positive_feedback:
        positive_feedback = ["No explicit positive feedback detected"]
    if not pricing_mentions:
        pricing_mentions = ["No explicit pricing mention detected"]
    if not pricing_feedback:
        pricing_feedback = ["No explicit pricing feedback detected"]
    if not exact_quote_candidates:
        exact_quote_candidates = ["No strong quote candidates detected"]

    actual_negative_confusing_feedback = [item for item in negative_confusing_feedback if item != "No explicit negative or confusing feedback detected"]
    actual_feature_requests = [item for item in feature_requests if item != "No explicit feature requests detected"]
    actual_positive_feedback = [item for item in positive_feedback if item != "No explicit positive feedback detected"]
    actual_pricing_mentions = [item for item in pricing_mentions if item != "No explicit pricing mention detected"]
    actual_pricing_feedback = [item for item in pricing_feedback if item != "No explicit pricing feedback detected"]
    action_items = _dedupe(
        _pick_sentences(sentences, _ACTION_ITEM_KEYWORDS, limit=5) + actual_feature_requests[:3] + _pick_sentences(sentences, ("next step", "follow up", "follow-up", "todo", "to do"), limit=3),
        limit=8,
    )
    if not action_items:
        action_items = ["No clear action items detected"]

    feature_score = len(actual_feature_requests)
    positive_score = len(actual_positive_feedback) + _score_word_hits(lower, _POSITIVE_KEYWORDS)
    negative_score = len(actual_negative_confusing_feedback) + _score_word_hits(lower, _NEGATIVE_OR_CONFUSING_KEYWORDS) + _score_word_hits(lower, _PAIN_KEYWORDS)
    pricing_score = len(actual_pricing_mentions)

    retention_likelihood = _clamp_score(5 + positive_score - negative_score + min(1, feature_score))
    pmf_score = _clamp_score(5 + positive_score - negative_score + min(2, feature_score) + min(1, pricing_score))
    would_pay = _would_pay(cleaned_transcript, actual_pricing_feedback, actual_positive_feedback, actual_negative_confusing_feedback)
    suggested_price = _suggested_price(actual_pricing_mentions, would_pay, retention_likelihood, pmf_score)

    analysis = HeuristicAnalysis(
        biggest_pain_points=biggest_pain_points,
        feature_requests=feature_requests,
        pricing_mentions=pricing_mentions,
        positive_feedback=positive_feedback,
        negative_confusing_feedback=negative_confusing_feedback,
        action_items=action_items,
        exact_quote_candidates=exact_quote_candidates,
        pricing_feedback=pricing_feedback,
        would_pay=would_pay,
        suggested_price=suggested_price,
        retention_likelihood=retention_likelihood,
        pmf_score=pmf_score,
    )

    if logger is not None:
        logger.info(
            "Heuristic analysis completed: %d pain points, %d feature requests, %d pricing mentions, %d action items",
            len(analysis.biggest_pain_points),
            len(analysis.feature_requests),
            len(analysis.pricing_mentions),
            len(analysis.action_items),
        )

    return analysis


def extract_interview_signals(transcript: str) -> dict[str, object]:
    cleaned_transcript = transcript.strip()
    lower = cleaned_transcript.lower()

    platform_mentions = []
    for needle, label in (
        ("tiktok", "TikTok"),
        ("instagram reels", "Instagram Reels"),
        ("youtube shorts", "YouTube Shorts"),
        ("linkedin", "LinkedIn"),
    ):
        if needle in lower:
            platform_mentions.append(label)

    goal_of_video = []
    for needle, label in (
        ("views", "Views"),
        ("engagement", "Engagement"),
        ("followers", "Followers"),
        ("brand awareness", "Brand Awareness"),
        ("sales", "Sales"),
        ("client approval", "Client Approval"),
    ):
        if needle in lower:
            goal_of_video.append(label)

    if len(set(platform_mentions)) > 1:
        platform = "Multiple"
    elif platform_mentions:
        platform = platform_mentions[0]
    else:
        platform = None

    if "wouldn't" in lower or "would not" in lower:
        posting_intent = "No"
    elif "i would post" in lower or "i'd post" in lower or "i would use this" in lower or "i'd use this" in lower or "i will post" in lower or "i'll post" in lower or "next video" in lower:
        posting_intent = "Definitely"
    else:
        posting_intent = None

    if "very confused" in lower:
        understanding = "Very Confused"
    elif any(phrase in lower for phrase in ("don't get", "do not get", "confusing", "unclear", "lost", "confused")):
        understanding = "Confused"
    elif any(phrase in lower for phrase in ("i get it", "makes sense", "understand", "clear", "straightforward")):
        understanding = "Yes"
    else:
        understanding = None

    return {
        "platform": platform,
        "goal_of_video": goal_of_video,
        "posting_intent": posting_intent,
        "understanding": understanding,
        "onboarding_completed": any(phrase in lower for phrase in ("onboarding", "on-board", "walkthrough", "setup", "signed up", "sign up", "completed setup")),
        "prompt_used": any(phrase in lower for phrase in ("prompt", "prompts", "script", "template", "chatgpt", "ai prompt")),
        "did_create_video": any(phrase in lower for phrase in ("created a video", "made a video", "posted a video", "uploaded a video")),
        "did_change_video": any(phrase in lower for phrase in ("major changes", "big changes", "dramatically", "completely changed", "minor changes", "small changes", "slightly changed", "gave confidence only", "confidence only", "no changes", "didn't change", "did not change")),
        "referral_offered": any(phrase in lower for phrase in ("referral", "refer", "introduce", "connect you", "put you in touch")),
        "follow_up_booked": any(phrase in lower for phrase in ("follow up", "follow-up", "book", "schedule", "next step", "check in", "reach out")),
    }
