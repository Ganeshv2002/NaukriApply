from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import JobCandidate, MatchScore, ProfileSettings, ResumeProfile
from .text_utils import normalize_text, parse_experience_ranges, tokenize


SOFTWARE_ROLE_HINTS = {
    "software",
    "developer",
    "engineer",
    "backend",
    "frontend",
    "full",
    "stack",
    "application",
    "programmer",
    "sde",
}

OBVIOUS_NON_MATCH_HINTS = {
    "sales recruiter",
    "hr recruiter",
    "telecaller",
    "bpo voice",
    "accountant",
    "warehouse",
    "delivery executive",
}


@dataclass(slots=True)
class CandidateScoringResult:
    candidate: JobCandidate
    score: MatchScore


def score_candidate(
    resume: ResumeProfile,
    candidate: JobCandidate,
    profile: ProfileSettings,
) -> MatchScore:
    title_blob = normalize_text(candidate.title)
    job_blob = normalize_text(" ".join([candidate.title, candidate.company, candidate.snippet, candidate.raw_text]))
    resume_titles = resume.titles or profile.search.keywords or ["software engineer"]

    title_score = max((fuzz.token_set_ratio(title_blob, normalize_text(title)) for title in resume_titles), default=0.0)
    title_component = round(min(title_score, 100.0) * 0.35, 2)

    resume_skills = {normalize_text(skill) for skill in resume.skills}
    matched_skills = sorted(skill for skill in resume_skills if skill and skill in job_blob)
    skill_ratio = 100.0 if not resume_skills else (len(matched_skills) / max(len(resume_skills), 1)) * 100.0
    skill_component = round(min(skill_ratio, 100.0) * 0.30, 2)

    search_keywords = [normalize_text(keyword) for keyword in profile.search.keywords]
    matched_keywords = sorted(keyword for keyword in search_keywords if keyword and keyword in job_blob)
    keyword_ratio = 100.0 if not search_keywords else (len(matched_keywords) / max(len(search_keywords), 1)) * 100.0
    keyword_component = round(min(keyword_ratio, 100.0) * 0.20, 2)

    experience_component, experience_reason = _score_experience(candidate, profile.target_experience_years)
    location_component, location_reason = _score_location(candidate, profile.search.locations)

    total = round(
        title_component
        + skill_component
        + keyword_component
        + experience_component
        + location_component,
        2,
    )

    reasons: list[str] = []
    if title_score >= 70:
        reasons.append("title aligns with target software roles")
    if matched_skills:
        reasons.append(f"resume skill overlap: {', '.join(matched_skills[:3])}")
    if matched_keywords:
        reasons.append(f"search keyword overlap: {', '.join(matched_keywords[:2])}")
    if experience_reason:
        reasons.append(experience_reason)
    if location_reason:
        reasons.append(location_reason)
    if not reasons:
        reasons.append("broad software-engineering candidate retained for review")

    return MatchScore(
        total=total,
        title_score=title_component,
        skill_score=skill_component,
        keyword_score=keyword_component,
        experience_score=experience_component,
        location_score=location_component,
        reasons=reasons[:4],
    )


def rank_candidates(
    resume: ResumeProfile,
    candidates: list[JobCandidate],
    profile: ProfileSettings,
) -> list[CandidateScoringResult]:
    ranked = [
        CandidateScoringResult(candidate=candidate, score=score_candidate(resume, candidate, profile))
        for candidate in candidates
        if not is_obvious_non_match(candidate)
    ]
    ranked.sort(key=lambda item: item.score.total, reverse=True)
    return ranked


def is_obvious_non_match(candidate: JobCandidate) -> bool:
    blob = normalize_text(" ".join([candidate.title, candidate.company, candidate.snippet, candidate.raw_text]))
    if any(hint in blob for hint in OBVIOUS_NON_MATCH_HINTS):
        return True
    title_tokens = tokenize(candidate.title)
    return not bool(title_tokens & SOFTWARE_ROLE_HINTS)


def _score_experience(candidate: JobCandidate, target_years: int) -> tuple[float, str]:
    ranges = parse_experience_ranges(" ".join([candidate.experience_text, candidate.snippet, candidate.raw_text]))
    if not ranges:
        return 6.0, "experience range not explicit; kept for manual review"

    for low, high in ranges:
        if low <= target_years <= high:
            return 10.0, f"experience range includes {target_years} years"
    return 0.0, "experience range appears outside the target"


def _score_location(candidate: JobCandidate, preferred_locations: list[str]) -> tuple[float, str]:
    if not preferred_locations:
        return 5.0, ""
    blob = normalize_text(" ".join([candidate.location_text, candidate.snippet, candidate.raw_text]))
    matches = [location for location in preferred_locations if normalize_text(location) in blob]
    if matches:
        return 5.0, f"preferred location matched: {matches[0]}"
    return 0.0, ""

