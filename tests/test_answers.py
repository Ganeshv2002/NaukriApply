from naukri_assistant.answers import AnswerMemory
from naukri_assistant.models import AnswerType


def test_exact_match_reuses_answer() -> None:
    memory = AnswerMemory()
    memory.remember(
        question="What is your notice period?",
        answer_value="30 days",
        answer_type=AnswerType.TEXT,
    )
    exact = memory.exact_match("What is your notice period?")
    assert exact is not None
    assert exact.answer == "30 days"


def test_fuzzy_match_suggests_without_exact_reuse() -> None:
    memory = AnswerMemory()
    memory.remember(
        question="What is your current notice period?",
        answer_value="30 days",
        answer_type=AnswerType.TEXT,
    )
    assert memory.exact_match("Current notice period?") is None
    fuzzy = memory.best_fuzzy_match("Current notice period?")
    assert fuzzy is not None
    assert fuzzy.answer.answer == "30 days"

