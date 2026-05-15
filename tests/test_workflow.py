from pathlib import Path

from rich.console import Console

from naukri_assistant.models import JobCandidate, ProfileSettings, ResumeProfile, SourcePath
from naukri_assistant.storage import LocalStore
from naukri_assistant.workflow import ReviewRunner


class UnknownOnlyBrowser:
    def discover_candidates(self, _profile):
        return [
            JobCandidate(
                stable_key="job:unknown",
                job_id="unknown",
                url="https://www.naukri.com/job-listings-software-engineer-acme-unknown",
                title="Software Engineer",
                company="Acme",
                raw_text="Software Engineer 1-3 years",
                experience_text="1-3 years",
            )
        ]

    def classify_candidate(self, _candidate):
        return SourcePath.UNKNOWN


def test_unknown_jobs_are_recorded_without_prompting(tmp_path: Path, monkeypatch) -> None:
    store = LocalStore(tmp_path)
    store.ensure_layout()
    runner = ReviewRunner(
        store=store,
        browser=UnknownOnlyBrowser(),
        console=Console(record=True),
    )
    profile = ProfileSettings(resume_path="resume.txt")
    resume = ResumeProfile(
        source_path="resume.txt",
        raw_text="Software Engineer with Python",
        normalized_text="software engineer with python",
        skills=["python"],
        titles=["software engineer"],
    )
    monkeypatch.setattr(
        "builtins.input",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("input should not be called")),
    )

    outcome = runner.run(profile=profile, resume=resume)
    history = store.load_history()

    assert outcome.unclassified == 1
    assert history[0].status.value == "unclassified"
