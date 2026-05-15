from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse, urlunparse


SPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+#./-]*")
EXPERIENCE_RANGE_RE = re.compile(
    r"(?P<low>\d+(?:\.\d+)?)\s*(?:-|to)\s*(?P<high>\d+(?:\.\d+)?)\s*(?:years?|yrs?)",
    re.IGNORECASE,
)
SINGLE_EXPERIENCE_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)",
    re.IGNORECASE,
)


def normalize_space(value: str) -> str:
    return SPACE_RE.sub(" ", value or "").strip()


def normalize_text(value: str) -> str:
    return normalize_space(value).lower()


def tokenize(value: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(value or "")}


def canonical_url(value: str) -> str:
    parsed = urlparse(value)
    clean = parsed._replace(fragment="")
    return urlunparse(clean)


def stable_hash(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def stable_job_key(job_id: str | None, url: str, title: str, company: str) -> str:
    if job_id:
        return f"job:{job_id}"
    basis = "|".join([canonical_url(url), normalize_text(title), normalize_text(company)])
    return f"url:{stable_hash(basis)}"


def parse_experience_ranges(text: str) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    for match in EXPERIENCE_RANGE_RE.finditer(text or ""):
        ranges.append((float(match.group("low")), float(match.group("high"))))
    if ranges:
        return ranges

    singles: list[tuple[float, float]] = []
    for match in SINGLE_EXPERIENCE_RE.finditer(text or ""):
        value = float(match.group("value"))
        singles.append((value, value))
    return singles

