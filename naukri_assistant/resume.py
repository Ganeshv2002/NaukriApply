from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from .models import ResumeProfile
from .text_utils import normalize_text, tokenize


KNOWN_SKILLS = [
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "node.js",
    "node",
    "django",
    "flask",
    "fastapi",
    "spring",
    "spring boot",
    "sql",
    "postgresql",
    "mysql",
    "mongodb",
    "aws",
    "azure",
    "gcp",
    "docker",
    "kubernetes",
    "git",
    "rest",
    "microservices",
    "html",
    "css",
    "c++",
    "c#",
    ".net",
]

KNOWN_TITLES = [
    "software engineer",
    "software developer",
    "backend developer",
    "full stack developer",
    "frontend developer",
    "application developer",
    "python developer",
    "java developer",
]

YEARS_PATTERN = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)


class ResumeReadError(ValueError):
    pass


def load_resume_profile(path_value: str) -> ResumeProfile:
    path = Path(path_value).expanduser()
    if not path.exists():
        raise ResumeReadError(f"Resume file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        raw_text = _read_pdf(path)
    elif suffix == ".docx":
        raw_text = _read_docx(path)
    elif suffix == ".txt":
        raw_text = path.read_text(encoding="utf-8")
    else:
        raise ResumeReadError("Unsupported resume format. Use PDF, DOCX, or TXT.")

    normalized = normalize_text(raw_text)
    if not normalized:
        raise ResumeReadError("Resume text is empty after extraction.")

    return ResumeProfile(
        source_path=str(path),
        raw_text=raw_text,
        normalized_text=normalized,
        skills=_extract_phrases(normalized, KNOWN_SKILLS),
        titles=_extract_phrases(normalized, KNOWN_TITLES),
        detected_experience_years=_extract_years(normalized),
    )


def _read_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text
    except Exception as exc:  # pragma: no cover - dependency-specific detail
        raise ResumeReadError(f"Could not read PDF resume: {exc}") from exc


def _read_docx(path: Path) -> str:
    try:
        document = Document(str(path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    except Exception as exc:  # pragma: no cover - dependency-specific detail
        raise ResumeReadError(f"Could not read DOCX resume: {exc}") from exc


def _extract_phrases(normalized_text: str, phrases: list[str]) -> list[str]:
    tokens = tokenize(normalized_text)
    found: list[str] = []
    for phrase in phrases:
        normalized_phrase = normalize_text(phrase)
        if " " not in normalized_phrase and normalized_phrase not in tokens:
            continue
        if normalized_phrase in normalized_text:
            found.append(phrase)
    return sorted(set(found))


def _extract_years(normalized_text: str) -> list[float]:
    years = {float(match.group("value")) for match in YEARS_PATTERN.finditer(normalized_text)}
    return sorted(years)

