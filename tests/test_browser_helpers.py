from pathlib import Path

from naukri_assistant.browser import NaukriBrowser
from naukri_assistant.models import ProfileSettings, SearchPreferences


def test_default_search_url_contains_keywords_and_experience(tmp_path: Path) -> None:
    browser = NaukriBrowser(tmp_path / "profile")
    profile = ProfileSettings(
        resume_path="resume.txt",
        target_experience_years=2,
        search=SearchPreferences(keywords=["software engineer", "python developer"]),
    )
    urls = browser.build_search_urls(profile)
    assert len(urls) == 1
    assert "experience=2" in urls[0]
    assert "software+engineer" in urls[0]
    assert "jobAge=7" in urls[0]


def test_explicit_search_url_reuses_last_week_filter(tmp_path: Path) -> None:
    browser = NaukriBrowser(tmp_path / "profile")
    profile = ProfileSettings(
        resume_path="resume.txt",
        search=SearchPreferences(
            search_urls=["https://www.naukri.com/search?k=software+engineer&jobAge=30"],
            max_posted_age_days=7,
        ),
    )
    urls = browser.build_search_urls(profile)
    assert urls == ["https://www.naukri.com/search?k=software+engineer&jobAge=7"]


def test_recent_posting_requires_visible_age_within_last_week() -> None:
    assert NaukriBrowser._is_recent_posting("Posted 2 days ago", max_days=7) is True
    assert NaukriBrowser._is_recent_posting("Posted yesterday", max_days=7) is True
    assert NaukriBrowser._is_recent_posting("Posted 1 week ago", max_days=7) is True
    assert NaukriBrowser._is_recent_posting("Posted 8 days ago", max_days=7) is False
    assert NaukriBrowser._is_recent_posting("Posted 2 weeks ago", max_days=7) is False
    assert NaukriBrowser._is_recent_posting("Age not shown", max_days=7) is False
