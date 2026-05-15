from __future__ import annotations

from dataclasses import dataclass
import logging

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .answers import AnswerMemory
from .browser import NaukriBrowser
from .logging_utils import LOGGER_NAME
from .matching import CandidateScoringResult, rank_candidates
from .models import ApplicationStatus, JobCandidate, ProfileSettings, SourcePath
from .reports import ExternalJobReportRow, ReportExporter
from .resume import ResumeProfile
from .storage import LocalStore


logger = logging.getLogger(LOGGER_NAME)


@dataclass(slots=True)
class ReviewOutcome:
    discovered: int = 0
    reviewable: int = 0
    processed: int = 0
    applied: int = 0
    skipped: int = 0
    deferred: int = 0
    manual_external: int = 0
    unclassified: int = 0
    failed: int = 0
    external_classified: int = 0
    external_exported: int = 0
    external_export_duplicates: int = 0
    report_path: str = ""


class ReviewRunner:
    def __init__(
        self,
        *,
        store: LocalStore,
        browser: NaukriBrowser,
        console: Console | None = None,
    ) -> None:
        self.store = store
        self.browser = browser
        self.console = console or Console()
        self.reporter = ReportExporter(store)

    def run(self, *, profile: ProfileSettings, resume: ResumeProfile) -> ReviewOutcome:
        answers = AnswerMemory(self.store.load_answers())
        discovered = self.browser.discover_candidates(profile)
        candidates = self._attach_history(discovered)
        candidates = [
            candidate
            for candidate in candidates
            if candidate.prior_status
            not in {
                ApplicationStatus.APPLIED,
                ApplicationStatus.SKIPPED,
                ApplicationStatus.MANUAL_EXTERNAL,
                ApplicationStatus.UNCLASSIFIED,
            }
        ]
        ranked = rank_candidates(resume, candidates, profile)
        outcome = ReviewOutcome(discovered=len(discovered), reviewable=len(ranked))
        external_rows: list[ExternalJobReportRow] = []
        logger.info(
            "Run started discovered=%s reviewable=%s",
            outcome.discovered,
            outcome.reviewable,
        )

        if not ranked:
            self.console.print("[yellow]No new matching candidates were found in the visible result pages.[/yellow]")
            self._finalize_reports(outcome, external_rows)
            return outcome

        for item in ranked:
            outcome.processed += 1
            candidate = self._classify(item.candidate)
            if candidate.source_path == SourcePath.EXTERNAL_REDIRECT:
                external_rows.append(self._external_row(candidate))
                outcome.external_classified += 1
            if candidate.source_path == SourcePath.UNKNOWN:
                self._record(
                    candidate,
                    ApplicationStatus.UNCLASSIFIED,
                    last_error="Apply path could not be classified from the visible job detail page.",
                )
                outcome.unclassified += 1
                logger.info("Candidate unclassified stable_key=%s", candidate.stable_key)
                continue
            self._render_candidate(candidate, item)
            action = self._ask_action(candidate)
            if action == "q":
                break
            if action == "o":
                self.browser.open_candidate(candidate)
                action = self._ask_action(candidate)
                if action == "q":
                    break
            if action == "s":
                self._record(candidate, ApplicationStatus.SKIPPED)
                outcome.skipped += 1
                logger.info("Candidate skipped stable_key=%s", candidate.stable_key)
                continue
            if action == "d":
                self._record(candidate, ApplicationStatus.DEFERRED)
                outcome.deferred += 1
                logger.info("Candidate deferred stable_key=%s", candidate.stable_key)
                continue
            if action != "a":
                self._record(candidate, ApplicationStatus.DEFERRED)
                outcome.deferred += 1
                logger.info("Candidate defaulted to deferred stable_key=%s", candidate.stable_key)
                continue

            self._record(candidate, ApplicationStatus.APPROVED)
            if candidate.source_path == SourcePath.EXTERNAL_REDIRECT:
                if profile.review.open_external_redirects:
                    self.browser.open_external_redirect(candidate)
                self._record(candidate, ApplicationStatus.MANUAL_EXTERNAL)
                outcome.manual_external += 1
                logger.info("External redirect queued for manual review stable_key=%s", candidate.stable_key)
                continue

            result = self.browser.attempt_direct_apply(candidate, answers)
            self.store.save_answers(answers.answers)
            if result.external_redirect:
                self._record(candidate, ApplicationStatus.MANUAL_EXTERNAL)
                outcome.manual_external += 1
            elif result.submitted:
                self._record(candidate, ApplicationStatus.APPLIED)
                outcome.applied += 1
                logger.info("Direct application marked applied stable_key=%s", candidate.stable_key)
            else:
                self._record(candidate, ApplicationStatus.FAILED, last_error=result.message)
                outcome.failed += 1
                self.console.print(f"[red]{result.message}[/red]")
                logger.warning("Direct application failed stable_key=%s message=%s", candidate.stable_key, result.message)

        self.store.save_answers(answers.answers)
        self._finalize_reports(outcome, external_rows)
        return outcome

    def _attach_history(self, candidates: list[JobCandidate]) -> list[JobCandidate]:
        history_by_key = {entry.stable_key: entry for entry in self.store.load_history()}
        enriched: list[JobCandidate] = []
        for candidate in candidates:
            entry = history_by_key.get(candidate.stable_key)
            if entry:
                enriched.append(candidate.model_copy(update={"prior_status": entry.status}))
            else:
                self._record(candidate, ApplicationStatus.SEEN)
                enriched.append(candidate.model_copy(update={"prior_status": ApplicationStatus.SEEN}))
        return enriched

    def _classify(self, candidate: JobCandidate) -> JobCandidate:
        source_path = self.browser.classify_candidate(candidate)
        return candidate.model_copy(update={"source_path": source_path})

    def _external_row(self, candidate: JobCandidate) -> ExternalJobReportRow:
        apply_link = self.browser.resolve_external_apply_link(candidate)
        return ExternalJobReportRow.from_candidate(candidate, apply_link=apply_link)

    def _finalize_reports(self, outcome: ReviewOutcome, external_rows: list[ExternalJobReportRow]) -> None:
        export_result = self.reporter.export_external_jobs(external_rows)
        outcome.external_exported = export_result.appended
        outcome.external_export_duplicates = export_result.duplicates
        payload = {
            "summary": {
                "discovered": outcome.discovered,
                "reviewable": outcome.reviewable,
                "processed": outcome.processed,
                "applied": outcome.applied,
                "skipped": outcome.skipped,
                "deferred": outcome.deferred,
                "manual_external": outcome.manual_external,
                "unclassified": outcome.unclassified,
                "failed": outcome.failed,
                "external_classified": outcome.external_classified,
                "external_exported": outcome.external_exported,
                "external_export_duplicates": outcome.external_export_duplicates,
            },
            "artifacts": {
                "external_jobs_workbook": str(export_result.path),
            },
        }
        outcome.report_path = str(self.reporter.export_run_report(payload))
        logger.info("Run finalized report_path=%s", outcome.report_path)

    def _record(
        self,
        candidate: JobCandidate,
        status: ApplicationStatus,
        *,
        last_error: str | None = None,
    ) -> None:
        self.store.upsert_history(
            stable_key=candidate.stable_key,
            job_id=candidate.job_id,
            url=candidate.url,
            title=candidate.title,
            company=candidate.company,
            status=status,
            last_error=last_error,
        )

    def _render_candidate(self, candidate: JobCandidate, item: CandidateScoringResult) -> None:
        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_row("Title", candidate.title)
        table.add_row("Company", candidate.company or "Unknown")
        table.add_row("Source", candidate.source_path.value)
        table.add_row("Score", f"{item.score.total:.2f}")
        table.add_row("Prior", candidate.prior_status.value if candidate.prior_status else "new")
        table.add_row("Why", "; ".join(item.score.reasons))
        self.console.print(Panel(table, title="Review candidate", expand=False))

    @staticmethod
    def _ask_action(candidate: JobCandidate) -> str:
        prompt = "Action [a=approve, s=skip, d=defer, o=open, q=quit]: "
        # answer = input(prompt).strip().lower()
        answer = "a"
        return answer[:1] if answer else "d"
