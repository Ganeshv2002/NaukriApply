from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import AnswerType, StoredAnswer, utc_now
from .text_utils import normalize_space, normalize_text


@dataclass(slots=True)
class AnswerSuggestion:
    answer: StoredAnswer
    similarity: float
    exact: bool


class AnswerMemory:
    def __init__(self, answers: list[StoredAnswer] | None = None) -> None:
        self.answers = answers or []

    def exact_match(
        self,
        question: str,
        *,
        answer_type: AnswerType | None = None,
        choices: list[str] | None = None,
    ) -> StoredAnswer | None:
        normalized = normalize_text(question)
        for answer in self.answers:
            if answer.normalized_question == normalized:
                if answer_type is not None and not self.is_compatible(
                    answer,
                    answer_type=answer_type,
                    choices=choices,
                ):
                    continue
                return answer
        return None

    def best_fuzzy_match(
        self,
        question: str,
        *,
        threshold: float = 82.0,
        answer_type: AnswerType | None = None,
        choices: list[str] | None = None,
    ) -> AnswerSuggestion | None:
        normalized = normalize_text(question)
        best: AnswerSuggestion | None = None
        for answer in self.answers:
            if answer_type is not None and not self.is_compatible(
                answer,
                answer_type=answer_type,
                choices=choices,
            ):
                continue
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
        existing = self.exact_match(question, answer_type=answer_type, choices=choices)
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

    @classmethod
    def is_compatible(
        cls,
        answer: StoredAnswer,
        *,
        answer_type: AnswerType,
        choices: list[str] | None = None,
    ) -> bool:
        if answer.answer_type != answer_type:
            return False
        return cls.answer_matches_choices(answer.answer, choices or [])

    @classmethod
    def compatible_answer_value(cls, answer: StoredAnswer, choices: list[str] | None = None):
        if not choices:
            return answer.answer
        if isinstance(answer.answer, list):
            matched_values = [cls._matching_choice(value, choices) for value in answer.answer]
            if any(value is None for value in matched_values):
                return answer.answer
            return matched_values
        matched = cls._matching_choice(answer.answer, choices)
        return matched if matched is not None else answer.answer

    @classmethod
    def answer_matches_choices(cls, answer_value, choices: list[str]) -> bool:
        if not choices:
            return True
        if isinstance(answer_value, list):
            return all(cls._matching_choice(value, choices) is not None for value in answer_value)
        return cls._matching_choice(answer_value, choices) is not None

    @staticmethod
    def _matching_choice(answer_value, choices: list[str]) -> str | None:
        target = normalize_text(str(answer_value))
        if not target:
            return None
        for choice in choices:
            if normalize_text(choice) == target:
                return normalize_space(choice)
        return None
