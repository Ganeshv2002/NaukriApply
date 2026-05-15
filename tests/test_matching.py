from naukri_assistant.matching import is_obvious_non_match, rank_candidates, score_candidate
from naukri_assistant.models import JobCandidate, ProfileSettings, ResumeProfile


def _resume() -> ResumeProfile:
    return ResumeProfile(
        source_path="resume.txt",
        raw_text="Software Engineer with 2 years in Python, FastAPI, SQL, AWS.",
        normalized_text="software engineer with 2 years in python fastapi sql aws",
        skills=["python", "fastapi", "sql", "aws"],
        titles=["software engineer"],
        detected_experience_years=[2.0],
    )


def _candidate(title: str, raw_text: str) -> JobCandidate:
    return JobCandidate(
        stable_key=title,
        url=f"https://example.test/{title}",
        title=title,
        company="Acme",
        snippet=raw_text,
        raw_text=raw_text,
        experience_text="1-3 years",
    )


def test_score_candidate_prefers_aligned_role() -> None:
    profile = ProfileSettings(resume_path="resume.txt")
    score = score_candidate(
        _resume(),
        _candidate("Software Engineer", "Python FastAPI SQL AWS 1-3 years"),
        profile,
    )
    assert score.total > 60
    assert any("experience range includes" in reason for reason in score.reasons)


def test_obvious_non_match_is_filtered() -> None:
    candidate = _candidate("Sales Recruiter", "sales recruiter")
    assert is_obvious_non_match(candidate) is True


def test_rank_candidates_sorts_descending() -> None:
    profile = ProfileSettings(resume_path="resume.txt")
    stronger = _candidate("Software Engineer", "Python SQL AWS 1-3 years")
    weaker = _candidate("Developer", "generic engineering 1-3 years")
    ranked = rank_candidates(_resume(), [weaker, stronger], profile)
    assert ranked[0].candidate.title == "Software Engineer"

