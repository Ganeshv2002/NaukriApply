from pathlib import Path

import pytest

from naukri_assistant.resume import ResumeReadError, load_resume_profile


def test_load_txt_resume(tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text(
        "Software Engineer with 2 years of Python, SQL, and FastAPI experience.",
        encoding="utf-8",
    )
    profile = load_resume_profile(str(resume_path))
    assert "python" in profile.skills
    assert "software engineer" in profile.titles
    assert 2.0 in profile.detected_experience_years


def test_empty_resume_rejected(tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.txt"
    resume_path.write_text("   ", encoding="utf-8")
    with pytest.raises(ResumeReadError):
        load_resume_profile(str(resume_path))


def test_unsupported_resume_rejected(tmp_path: Path) -> None:
    resume_path = tmp_path / "resume.rtf"
    resume_path.write_text("sample", encoding="utf-8")
    with pytest.raises(ResumeReadError):
        load_resume_profile(str(resume_path))

