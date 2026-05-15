from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console
from rich.table import Table

from .answers import AnswerMemory
from .browser import NaukriBrowser
from .logging_utils import configure_logging
from .models import AnswerType, ProfileSettings, SearchPreferences
from .resume import ResumeReadError, load_resume_profile
from .storage import LocalStore
from .workflow import ReviewRunner


console = Console()


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "init":
        _cmd_init()
    elif args.command == "login":
        _cmd_login()
    elif args.command == "run":
        _cmd_run()
    elif args.command == "answers":
        _cmd_answers(args)
    elif args.command == "history":
        _cmd_history(args)
    else:
        parser.print_help()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="naukri-assistant")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("init")
    subparsers.add_parser("login")
    subparsers.add_parser("run")

    answers = subparsers.add_parser("answers")
    answers_sub = answers.add_subparsers(dest="answers_command", required=True)
    answers_sub.add_parser("list")
    add_answer = answers_sub.add_parser("add")
    add_answer.add_argument("--question", required=True)
    add_answer.add_argument("--answer", required=True)
    add_answer.add_argument(
        "--type",
        choices=[item.value for item in AnswerType],
        default=AnswerType.TEXT.value,
    )

    history = subparsers.add_parser("history")
    history_sub = history.add_subparsers(dest="history_command", required=True)
    history_sub.add_parser("list")
    return parser


def _cmd_init() -> None:
    store = LocalStore()
    store.ensure_layout()
    configure_logging(store)

    resume_path = _clean_path_input(input("Resume path (PDF, DOCX, or TXT): "))
    keywords = _split_csv(
        input(
            "Target keywords [software engineer, software developer, backend developer, full stack developer]: "
        ).strip()
    )
    locations = _split_csv(input("Preferred locations (optional, comma-separated): ").strip())
    urls = _split_csv(input("Explicit Naukri search URLs (optional, comma-separated): ").strip())
    max_pages = _prompt_int("Result pages per run", default=1, minimum=1, maximum=10)
    max_jobs = _prompt_int("Max jobs per run", default=40, minimum=1, maximum=500)

    search = SearchPreferences(
        keywords=keywords or SearchPreferences().keywords,
        locations=locations,
        search_urls=urls,
        max_posted_age_days=7,
        max_result_pages=max_pages,
        max_jobs_per_run=max_jobs,
    )
    profile = ProfileSettings(resume_path=resume_path, search=search)
    try:
        load_resume_profile(profile.resume_path)
    except ResumeReadError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    store.save_profile(profile)
    console.print("[green]Profile created under data/profile.json.[/green]")


def _cmd_login() -> None:
    store = LocalStore()
    store.ensure_layout()
    configure_logging(store)
    with NaukriBrowser(store.browser_profile_dir) as browser:
        browser.open_login()
        input("Complete Naukri login in the browser, then press Enter here to store the session locally.")
    console.print("[green]Browser session profile updated.[/green]")


def _cmd_run() -> None:
    store = LocalStore()
    store.ensure_layout()
    configure_logging(store)
    if not store.profile_exists():
        console.print("[red]No profile found. Run `naukri-assistant init` first.[/red]")
        return
    profile = store.load_profile()
    try:
        resume = load_resume_profile(profile.resume_path)
    except ResumeReadError as exc:
        console.print(f"[red]{exc}[/red]")
        return

    with NaukriBrowser(store.browser_profile_dir) as browser:
        runner = ReviewRunner(store=store, browser=browser, console=console)
        outcome = runner.run(profile=profile, resume=resume)
    console.print(
        f"[green]Processed {outcome.processed} candidates. "
        f"Applied {outcome.applied}, skipped {outcome.skipped}, deferred {outcome.deferred}, "
        f"manual external {outcome.manual_external}, unclassified {outcome.unclassified}, failed {outcome.failed}. "
        f"External rows exported {outcome.external_exported}, duplicate exports skipped {outcome.external_export_duplicates}.[/green]"
    )
    if outcome.report_path:
        console.print(f"[cyan]Run report:[/cyan] {outcome.report_path}")


def _cmd_answers(args: argparse.Namespace) -> None:
    store = LocalStore()
    configure_logging(store)
    memory = AnswerMemory(store.load_answers())
    if args.answers_command == "list":
        table = Table("Question", "Answer", "Type", "Choices")
        for answer in memory.answers:
            table.add_row(
                answer.raw_questions[0] if answer.raw_questions else answer.normalized_question,
                str(answer.answer),
                answer.answer_type.value,
                ", ".join(answer.choices),
            )
        console.print(table)
        return
    if args.answers_command == "add":
        memory.remember(
            question=args.question,
            answer_value=args.answer,
            answer_type=AnswerType(args.type),
        )
        store.save_answers(memory.answers)
        console.print("[green]Saved reusable answer.[/green]")


def _cmd_history(args: argparse.Namespace) -> None:
    store = LocalStore()
    configure_logging(store)
    history = store.load_history()
    table = Table("Status", "Title", "Company", "Updated")
    for entry in sorted(history, key=lambda item: item.updated_at, reverse=True):
        table.add_row(
            entry.status.value,
            entry.title,
            entry.company or "Unknown",
            entry.updated_at.isoformat(),
        )
    console.print(table)


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _clean_path_input(raw: str) -> str:
    cleaned = raw.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
        return cleaned[1:-1].strip()
    return cleaned


def _prompt_int(label: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = input(f"{label} [{default}]: ").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


if __name__ == "__main__":
    main()
