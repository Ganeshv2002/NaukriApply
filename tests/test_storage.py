from pathlib import Path

from naukri_assistant.models import ApplicationStatus, ProfileSettings
from naukri_assistant.storage import LocalStore


def test_profile_round_trip(tmp_path: Path) -> None:
    store = LocalStore(tmp_path)
    profile = ProfileSettings(resume_path="resume.txt")
    store.save_profile(profile)
    loaded = store.load_profile()
    assert loaded.resume_path == "resume.txt"


def test_history_upsert_updates_status(tmp_path: Path) -> None:
    store = LocalStore(tmp_path)
    store.upsert_history(
        stable_key="job:1",
        job_id="1",
        url="https://example.test/job",
        title="Software Engineer",
        company="Acme",
        status=ApplicationStatus.SEEN,
    )
    store.upsert_history(
        stable_key="job:1",
        job_id="1",
        url="https://example.test/job",
        title="Software Engineer",
        company="Acme",
        status=ApplicationStatus.APPLIED,
    )
    history = store.load_history()
    assert len(history) == 1
    assert history[0].status == ApplicationStatus.APPLIED

