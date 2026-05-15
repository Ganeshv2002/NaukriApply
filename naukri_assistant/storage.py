from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import TypeAdapter

from .models import (
    ApplicationHistoryEntry,
    ApplicationStatus,
    ProfileSettings,
    StoredAnswer,
    utc_now,
)


PROFILE_ADAPTER = TypeAdapter(ProfileSettings)
ANSWER_LIST_ADAPTER = TypeAdapter(list[StoredAnswer])
HISTORY_LIST_ADAPTER = TypeAdapter(list[ApplicationHistoryEntry])


class LocalStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path.cwd()
        self.data_dir = self.root / "data"
        self.profile_path = self.data_dir / "profile.json"
        self.answers_path = self.data_dir / "answers.json"
        self.history_path = self.data_dir / "history.json"
        self.browser_profile_dir = self.data_dir / "browser-profile"
        self.reports_dir = self.data_dir / "reports"
        self.logs_dir = self.data_dir / "logs"
        self.external_jobs_report_path = self.reports_dir / "external-review-needed.xlsx"
        self.latest_run_report_path = self.reports_dir / "latest-run-report.json"

    def ensure_layout(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        if not self.answers_path.exists():
            self._write_json(self.answers_path, [])
        if not self.history_path.exists():
            self._write_json(self.history_path, [])

    def profile_exists(self) -> bool:
        return self.profile_path.exists()

    def load_profile(self) -> ProfileSettings:
        return PROFILE_ADAPTER.validate_python(self._read_json(self.profile_path))

    def save_profile(self, profile: ProfileSettings) -> None:
        self.ensure_layout()
        self._write_json(self.profile_path, profile.model_dump(mode="json"))

    def load_answers(self) -> list[StoredAnswer]:
        self.ensure_layout()
        return ANSWER_LIST_ADAPTER.validate_python(self._read_json(self.answers_path))

    def save_answers(self, answers: Iterable[StoredAnswer]) -> None:
        self.ensure_layout()
        payload = [answer.model_dump(mode="json") for answer in answers]
        self._write_json(self.answers_path, payload)

    def load_history(self) -> list[ApplicationHistoryEntry]:
        self.ensure_layout()
        return HISTORY_LIST_ADAPTER.validate_python(self._read_json(self.history_path))

    def save_history(self, entries: Iterable[ApplicationHistoryEntry]) -> None:
        self.ensure_layout()
        payload = [entry.model_dump(mode="json") for entry in entries]
        self._write_json(self.history_path, payload)

    def find_history(self, stable_key: str) -> ApplicationHistoryEntry | None:
        for entry in self.load_history():
            if entry.stable_key == stable_key:
                return entry
        return None

    def upsert_history(
        self,
        *,
        stable_key: str,
        job_id: str | None,
        url: str,
        title: str,
        company: str,
        status: ApplicationStatus,
        last_error: str | None = None,
    ) -> ApplicationHistoryEntry:
        history = self.load_history()
        now = utc_now()
        for index, entry in enumerate(history):
            if entry.stable_key != stable_key:
                continue
            updated = entry.model_copy(
                update={
                    "job_id": job_id or entry.job_id,
                    "url": url,
                    "title": title,
                    "company": company,
                    "status": status,
                    "updated_at": now,
                    "last_error": last_error,
                }
            )
            history[index] = updated
            self.save_history(history)
            return updated

        created = ApplicationHistoryEntry(
            stable_key=stable_key,
            job_id=job_id,
            url=url,
            title=title,
            company=company,
            status=status,
            first_seen_at=now,
            updated_at=now,
            last_error=last_error,
        )
        history.append(created)
        self.save_history(history)
        return created

    @staticmethod
    def _read_json(path: Path):
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
