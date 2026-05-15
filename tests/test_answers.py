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


def test_exact_match_can_require_answer_type() -> None:
    memory = AnswerMemory()
    question = "How many years of experience do you have in Nextjs?"
    memory.remember(
        question=question,
        answer_value="2",
        answer_type=AnswerType.TEXT,
    )

    assert (
        memory.exact_match(
            question,
            answer_type=AnswerType.SINGLE_SELECT,
            choices=["No experience", "1-3 years"],
        )
        is None
    )

    memory.remember(
        question=question,
        answer_value="1-3 years",
        answer_type=AnswerType.SINGLE_SELECT,
        choices=["No experience", "1-3 years"],
    )

    assert len(memory.answers) == 2
    assert memory.exact_match(question, answer_type=AnswerType.TEXT).answer == "2"
    select_match = memory.exact_match(
        question,
        answer_type=AnswerType.SINGLE_SELECT,
        choices=["No experience", "1-3 years"],
    )
    assert select_match is not None
    assert select_match.answer == "1-3 years"


def test_exact_match_requires_saved_answer_to_match_current_choices() -> None:
    memory = AnswerMemory()
    question = "Are you willing to relocate?"
    memory.remember(
        question=question,
        answer_value="Maybe",
        answer_type=AnswerType.SINGLE_SELECT,
        choices=["Maybe", "No"],
    )

    assert (
        memory.exact_match(
            question,
            answer_type=AnswerType.SINGLE_SELECT,
            choices=["Yes", "No"],
        )
        is None
    )

    memory.remember(
        question=question,
        answer_value="Yes",
        answer_type=AnswerType.SINGLE_SELECT,
        choices=["Yes", "No"],
    )

    assert len(memory.answers) == 2
    current_match = memory.exact_match(
        question,
        answer_type=AnswerType.SINGLE_SELECT,
        choices=["Yes", "No"],
    )
    old_match = memory.exact_match(
        question,
        answer_type=AnswerType.SINGLE_SELECT,
        choices=["Maybe", "No"],
    )
    assert current_match is not None
    assert current_match.answer == "Yes"
    assert old_match is not None
    assert old_match.answer == "Maybe"
