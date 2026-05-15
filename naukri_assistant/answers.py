from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import AnswerType, StoredAnswer, utc_now
from .text_utils import normalize_text


@dataclass(slots=True)
class AnswerSuggestion:
    answer: StoredAnswer
    similarity: float
    exact: bool


class AnswerMemory:
    def __init__(self, answers: list[StoredAnswer] | None = None) -> None:
        self.answers = answers or []

    def exact_match(self, question: str) -> StoredAnswer | None:
        normalized = normalize_text(question)
        for answer in self.answers:
            if answer.normalized_question == normalized:
                return answer
        return None

    def best_fuzzy_match(self, question: str, *, threshold: float = 82.0) -> AnswerSuggestion | None:
        normalized = normalize_text(question)
        best: AnswerSuggestion | None = None
        for answer in self.answers:
            similarity = fuzz.token_set_ratio(normalized, answer.normalized_question)
            candidate = AnswerSuggestion(answer=answer, similarity=similarity, exact=False)
            if similarity >= threshold and (best is None or similarity > best.similarity):
                best = candidate
        return best

    def remember(
        self,
        *,
        question: str,
        answer_value,
        answer_type: AnswerType,
        choices: list[str] | None = None,
    ) -> StoredAnswer:
        normalized = normalize_text(question)
        existing = self.exact_match(question)
        raw_questions = [question]
        if existing:
            raw_questions = list(dict.fromkeys([*existing.raw_questions, question]))
            updated = existing.model_copy(
                update={
                    "answer": answer_value,
                    "answer_type": answer_type,
                    "choices": choices or existing.choices,
                    "raw_questions": raw_questions,
                    "last_used_at": utc_now(),
                }
            )
            index = self.answers.index(existing)
            self.answers[index] = updated
            return updated

        created = StoredAnswer(
            normalized_question=normalized,
            raw_questions=raw_questions,
            answer=answer_value,
            answer_type=answer_type,
            choices=choices or [],
            last_used_at=utc_now(),
        )
        self.answers.append(created)
        return created

    def touch(self, answer: StoredAnswer) -> StoredAnswer:
        updated = answer.model_copy(update={"last_used_at": utc_now()})
        index = self.answers.index(answer)
        self.answers[index] = updated
        return updated

