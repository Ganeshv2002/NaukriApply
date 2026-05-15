from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnswerType(StrEnum):
    TEXT = "text"
    YES_NO = "yes-no"
    SINGLE_SELECT = "single-select"
    MULTI_SELECT = "multi-select"
    NUMERIC = "numeric"


class ApplicationStatus(StrEnum):
    SEEN = "seen"
    APPROVED = "approved"
    APPLIED = "applied"
    SKIPPED = "skipped"
    DEFERRED = "deferred"
    MANUAL_EXTERNAL = "manual_external"
    UNCLASSIFIED = "unclassified"
    FAILED = "failed"


class SourcePath(StrEnum):
    NAUKRI_DIRECT = "naukri_direct"
    EXTERNAL_REDIRECT = "external_redirect"
    UNKNOWN = "unknown"


class SearchPreferences(BaseModel):
    keywords: list[str] = Field(
        default_factory=lambda: [
            "software engineer",
            "software developer",
            "backend developer",
            "full stack developer",
        ]
    )
    locations: list[str] = Field(default_factory=list)
    search_urls: list[str] = Field(default_factory=list)
    max_posted_age_days: int = Field(default=7, ge=1, le=30)
    max_result_pages: int = Field(default=1, ge=1, le=10)
    max_jobs_per_run: int = Field(default=40, ge=1, le=500)


class ReviewSettings(BaseModel):
    open_external_redirects: bool = True
    show_prior_status: bool = True


class ProfileSettings(BaseModel):
    resume_path: str
    target_experience_years: int = Field(default=2, ge=0, le=50)
    search: SearchPreferences = Field(default_factory=SearchPreferences)
    review: ReviewSettings = Field(default_factory=ReviewSettings)


class ResumeProfile(BaseModel):
    source_path: str
    raw_text: str
    normalized_text: str
    skills: list[str] = Field(default_factory=list)
    titles: list[str] = Field(default_factory=list)
    detected_experience_years: list[float] = Field(default_factory=list)


class JobCandidate(BaseModel):
    stable_key: str
    job_id: str | None = None
    url: str
    title: str
    company: str = ""
    snippet: str = ""
    raw_text: str = ""
    experience_text: str = ""
    location_text: str = ""
    source_path: SourcePath = SourcePath.UNKNOWN
    search_url: str | None = None
    prior_status: ApplicationStatus | None = None


class MatchScore(BaseModel):
    total: float
    title_score: float
    skill_score: float
    keyword_score: float
    experience_score: float
    location_score: float
    reasons: list[str] = Field(default_factory=list)


class StoredAnswer(BaseModel):
    normalized_question: str
    raw_questions: list[str] = Field(default_factory=list)
    answer: Any
    answer_type: AnswerType = AnswerType.TEXT
    choices: list[str] = Field(default_factory=list)
    last_used_at: datetime = Field(default_factory=utc_now)


class ApplicationAttempt(BaseModel):
    candidate_key: str
    status: ApplicationStatus
    attempted_at: datetime = Field(default_factory=utc_now)
    message: str = ""


class ApplicationHistoryEntry(BaseModel):
    stable_key: str
    job_id: str | None = None
    url: str
    title: str
    company: str = ""
    status: ApplicationStatus
    first_seen_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    last_error: str | None = None
