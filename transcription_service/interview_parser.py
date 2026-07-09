from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_SPEAKER_LINE_RE = re.compile(
    r"^(?P<speaker>(?:interviewer|participant|respondent|speaker\s*\d+|speaker|you|me|them))\s*:\s*(?P<text>.+)$",
    re.IGNORECASE,
)
_QUESTION_STARTERS = (
    r"before we start",
    r"let's start",
    r"to start",
    r"can you",
    r"could you",
    r"would you",
    r"do you",
    r"did you",
    r"have you",
    r"are you",
    r"is it",
    r"what's",
    r"what is",
    r"what are",
    r"what do",
    r"what did",
    r"what would",
    r"what kind of",
    r"what was",
    r"how do",
    r"how did",
    r"how would",
    r"how much",
    r"how often",
    r"where do",
    r"where did",
    r"where are",
    r"why do",
    r"why did",
    r"tell me",
    r"walk me through",
)
_ANSWER_STARTERS = (
    "yes",
    "yeah",
    "yep",
    "no",
    "nope",
    "well",
    "so",
    "i",
    "uh",
    "um",
    "sure",
    "absolutely",
)
_QUESTION_RE = re.compile(r"^(?:" + "|".join(_QUESTION_STARTERS) + r")\b", re.IGNORECASE)
_QUESTION_SPLIT_RE = re.compile(r"\s+(?=(?:yes|yeah|yep|no|nope|well|so|i\b|uh\b|um\b|sure\b|absolutely\b))", re.IGNORECASE)


@dataclass(frozen=True)
class InterviewQAPair:
    index: int
    question: str
    answer: str
    question_start_index: int
    answer_start_index: int
    confidence: float
    question_type: str = "question"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "question": self.question,
            "answer": self.answer,
            "question_start_index": self.question_start_index,
            "answer_start_index": self.answer_start_index,
            "confidence": self.confidence,
            "question_type": self.question_type,
        }


def _split_sentences(text: str) -> list[str]:
    return [sentence.strip(" \t\r") for sentence in _SENTENCE_SPLIT_RE.split(text.strip()) if sentence and sentence.strip(" \t\r")]


def _is_question_text(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False
    if "?" in lowered:
        return True
    if _QUESTION_RE.match(lowered):
        return True
    return any(lowered.startswith(starter) for starter in _QUESTION_STARTERS)


def _split_question_answer(text: str) -> tuple[str, str]:
    cleaned = text.strip()
    if not cleaned:
        return "", ""

    if "?" in cleaned:
        question_part, answer_part = cleaned.split("?", 1)
        question_part = f"{question_part.strip()}?"
        answer_part = answer_part.strip()
        if answer_part:
            return question_part, answer_part
        return question_part, ""

    match = _QUESTION_RE.search(cleaned)
    if not match:
        return cleaned, ""

    question_part = cleaned[: match.end()].strip(" ,")
    remainder = cleaned[match.end() :].strip(" ,")
    if remainder and remainder.lower().startswith(_ANSWER_STARTERS):
        return question_part, remainder
    return cleaned, ""


def _looks_like_answer(text: str) -> bool:
    lowered = text.lower().strip()
    if not lowered:
        return False
    if lowered.startswith(_ANSWER_STARTERS):
        return True
    return bool(re.search(r"\b(i|we|they|it|my|our|the)\b", lowered))


def _parse_speaker_lines(lines: list[str]) -> list[InterviewQAPair]:
    pairs: list[InterviewQAPair] = []
    current_question = ""
    current_answer = ""
    current_question_start = 0
    current_answer_start = 0
    index = 0
    cursor = 0

    def flush() -> None:
        nonlocal index, current_question, current_answer, current_question_start, current_answer_start
        question = current_question.strip()
        answer = current_answer.strip()
        if not question and not answer:
            return
        pairs.append(
            InterviewQAPair(
                index=index,
                question=question or "Opening context",
                answer=answer,
                question_start_index=current_question_start,
                answer_start_index=current_answer_start,
                confidence=0.9 if question else 0.5,
            )
        )
        index += 1
        current_question = ""
        current_answer = ""

    for line in lines:
        match = _SPEAKER_LINE_RE.match(line)
        if not match:
            if current_question:
                if current_answer:
                    current_answer += " " + line.strip()
                else:
                    current_answer = line.strip()
            elif pairs:
                last = pairs[-1]
                pairs[-1] = InterviewQAPair(
                    index=last.index,
                    question=last.question,
                    answer=(last.answer + " " + line.strip()).strip(),
                    question_start_index=last.question_start_index,
                    answer_start_index=last.answer_start_index,
                    confidence=last.confidence,
                    question_type=last.question_type,
                )
            cursor += len(line) + 1
            continue

        speaker = match.group("speaker").strip().lower()
        text = match.group("text").strip()
        if speaker in {"interviewer", "speaker 1", "speaker1", "you", "me"}:
            if current_question or current_answer:
                flush()
            current_question = text
            current_question_start = cursor
            current_answer_start = cursor + len(text) + 1
            if _is_question_text(text):
                question_text, answer_text = _split_question_answer(text)
                current_question = question_text
                current_answer = answer_text
        else:
            if current_question:
                current_answer = (current_answer + " " + text).strip()
            else:
                current_question = "Opening context"
                current_question_start = cursor
                current_answer = text
                current_answer_start = cursor + len(text)
        cursor += len(line) + 1

    flush()
    return pairs


def parse_interview_qa_pairs(transcript: str) -> list[InterviewQAPair]:
    cleaned = transcript.strip()
    if not cleaned:
        return []

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if any(_SPEAKER_LINE_RE.match(line) for line in lines):
        pairs = _parse_speaker_lines(lines)
        if pairs:
            return pairs

    sentences = _split_sentences(cleaned)
    pairs: list[InterviewQAPair] = []
    current_question = ""
    current_answer_parts: list[str] = []
    current_question_start = 0
    current_answer_start = 0
    cursor = 0

    def flush() -> None:
        nonlocal current_question, current_answer_parts, current_question_start, current_answer_start
        question = current_question.strip()
        answer = " ".join(part.strip() for part in current_answer_parts if part.strip()).strip()
        if not question and not answer:
            return
        pairs.append(
            InterviewQAPair(
                index=len(pairs),
                question=question or "Opening context",
                answer=answer,
                question_start_index=current_question_start,
                answer_start_index=current_answer_start,
                confidence=0.88 if question else 0.5,
            )
        )
        current_question = ""
        current_answer_parts = []

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        question_text, answer_text = _split_question_answer(sentence)
        if _is_question_text(question_text):
            if current_question or current_answer_parts:
                flush()
            current_question = question_text
            current_question_start = cursor
            current_answer_start = cursor + len(question_text) + 1
            if answer_text:
                if _looks_like_answer(answer_text):
                    current_answer_parts.append(answer_text)
                else:
                    current_question = sentence
                    current_answer_parts = []
        else:
            if current_question:
                current_answer_parts.append(sentence)
            else:
                current_question = "Opening context"
                current_question_start = cursor
                current_answer_parts = [sentence]
                current_answer_start = cursor

        cursor += len(sentence) + 1

    flush()

    if not pairs:
        return [
            InterviewQAPair(
                index=0,
                question="Opening context",
                answer=cleaned,
                question_start_index=0,
                answer_start_index=0,
                confidence=0.4,
            )
        ]
    return pairs
