from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

from playwright.sync_api import BrowserContext, Locator, Page, TimeoutError, sync_playwright

from .answers import AnswerMemory
from .logging_utils import LOGGER_NAME
from .models import AnswerType, JobCandidate, ProfileSettings, SourcePath
from .text_utils import canonical_url, normalize_space, stable_job_key


logger = logging.getLogger(LOGGER_NAME)


@dataclass(slots=True)
class ApplicationResult:
    submitted: bool
    external_redirect: bool = False
    message: str = ""


class BrowserAutomationError(RuntimeError):
    pass


class NaukriBrowser:
    def __init__(self, browser_profile_dir: Path, *, headless: bool = False) -> None:
        self.browser_profile_dir = browser_profile_dir
        self.headless = headless
        self._playwright = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    def __enter__(self) -> "NaukriBrowser":
        self.browser_profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self.context = self._playwright.chromium.launch_persistent_context(
            str(self.browser_profile_dir),
            headless=self.headless,
            viewport={"width": 1440, "height": 960},
        )
        pages = self.context.pages
        self.page = pages[0] if pages else self.context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.context:
            self.context.close()
        if self._playwright:
            self._playwright.stop()

    @property
    def active_page(self) -> Page:
        if self.page is None:
            raise BrowserAutomationError("Browser page is not initialized.")
        return self.page

    def open_login(self) -> None:
        logger.info("Opening Naukri login page")
        self.active_page.goto("https://www.naukri.com/nlogin/login", wait_until="domcontentloaded")

    def build_search_urls(self, profile: ProfileSettings) -> list[str]:
        if profile.search.search_urls:
            return [
                self._with_job_age_filter(search_url, profile.search.max_posted_age_days)
                for search_url in profile.search.search_urls
            ]
        keyword_blob = ", ".join(profile.search.keywords) or "software engineer"
        query = quote_plus(keyword_blob)
        search_url = f"https://www.naukri.com/search?k={query}&experience={profile.target_experience_years}"
        return [self._with_job_age_filter(search_url, profile.search.max_posted_age_days)]

    def discover_candidates(self, profile: ProfileSettings) -> list[JobCandidate]:
        collected: dict[str, JobCandidate] = {}
        for search_url in self.build_search_urls(profile):
            logger.info("Opening search url=%s", search_url)
            self.active_page.goto(search_url, wait_until="domcontentloaded")
            self.active_page.wait_for_timeout(1800)
            for page_index in range(profile.search.max_result_pages):
                extracted = self._extract_visible_candidates(
                    search_url,
                    max_posted_age_days=profile.search.max_posted_age_days,
                )
                logger.info(
                    "Extracted visible candidates count=%s search_url=%s page_index=%s",
                    len(extracted),
                    search_url,
                    page_index,
                )
                for candidate in extracted:
                    if candidate.stable_key in collected:
                        logger.info("Skipped duplicate candidate stable_key=%s", candidate.stable_key)
                        continue
                    collected[candidate.stable_key] = candidate
                    if len(collected) >= profile.search.max_jobs_per_run:
                        return list(collected.values())
                if page_index + 1 >= profile.search.max_result_pages:
                    break
                if not self._goto_next_results_page():
                    break
        return list(collected.values())

    def classify_candidate(self, candidate: JobCandidate) -> SourcePath:
        self.active_page.goto(candidate.url, wait_until="domcontentloaded")
        self.active_page.wait_for_timeout(1400)
        if self._visible_text_exists(r"apply on company website"):
            logger.info("Classified external redirect stable_key=%s", candidate.stable_key)
            return SourcePath.EXTERNAL_REDIRECT
        if self._find_apply_button():
            logger.info("Classified direct apply stable_key=%s", candidate.stable_key)
            return SourcePath.NAUKRI_DIRECT
        logger.info("Could not classify apply path stable_key=%s", candidate.stable_key)
        return SourcePath.UNKNOWN

    def open_candidate(self, candidate: JobCandidate) -> None:
        self.active_page.goto(candidate.url, wait_until="domcontentloaded")
        self.active_page.wait_for_timeout(1200)

    def attempt_direct_apply(self, candidate: JobCandidate, answer_memory: AnswerMemory) -> ApplicationResult:
        self.open_candidate(candidate)
        if self._visible_text_exists(r"apply on company website"):
            logger.info("Direct apply attempt changed to external redirect stable_key=%s", candidate.stable_key)
            return ApplicationResult(submitted=False, external_redirect=True, message="Job redirects to company website.")

        button = self._find_apply_button()
        if button is None:
            logger.warning("No apply button visible stable_key=%s", candidate.stable_key)
            return ApplicationResult(submitted=False, message="No visible Naukri apply button was found.")

        click_error = self._click_with_overlay_recovery(
            button,
            action_label="initial Apply",
            candidate=candidate,
        )
        if click_error:
            return ApplicationResult(submitted=False, message=click_error)
        self.active_page.wait_for_timeout(1500)
        if self._application_confirmation_visible():
            logger.info("Application confirmation detected after initial apply stable_key=%s", candidate.stable_key)
            return ApplicationResult(submitted=True, message="Application submission was confirmed in-page.")

        chatbot_result = self._complete_chatbot_questionnaire(answer_memory, candidate)
        if chatbot_result is not None:
            return chatbot_result

        self._fill_visible_questionnaire(answer_memory)
        if self._application_confirmation_visible():
            logger.info("Application confirmation detected after questionnaire fill stable_key=%s", candidate.stable_key)
            return ApplicationResult(submitted=True, message="Application submission was confirmed in-page.")

        final_submit = self._find_submit_button()
        if final_submit is None:
            logger.warning("No final submit button visible stable_key=%s", candidate.stable_key)
            self._log_dom_snapshot("no_final_submit_button", candidate)
            return ApplicationResult(
                submitted=False,
                message="Apply action opened, but neither a chatbot flow nor a final submit button was detected.",
            )

        click_error = self._click_with_overlay_recovery(
            final_submit,
            action_label="final Submit",
            candidate=candidate,
        )
        if click_error:
            return ApplicationResult(submitted=False, message=click_error)
        self.active_page.wait_for_timeout(1800)
        if self._application_confirmation_visible():
            logger.info("Application confirmation detected stable_key=%s", candidate.stable_key)
            return ApplicationResult(submitted=True, message="Application submission was confirmed in-page.")
        logger.info("Final submit clicked without explicit confirmation stable_key=%s", candidate.stable_key)
        return ApplicationResult(
            submitted=True,
            message="Final submit was clicked; verify the browser page if Naukri needs extra confirmation.",
        )

    def open_external_redirect(self, candidate: JobCandidate) -> None:
        self.open_candidate(candidate)
        locator = self.active_page.get_by_text(re.compile(r"apply on company website", re.I))
        if locator.count():
            locator.first.click()
            self.active_page.wait_for_timeout(1200)

    def resolve_external_apply_link(self, candidate: JobCandidate) -> str:
        self.open_candidate(candidate)
        locator = self.active_page.get_by_text(re.compile(r"apply on company website", re.I))
        if not locator.count():
            return candidate.url
        button_or_link = locator.first
        href = button_or_link.get_attribute("href")
        if href:
            return canonical_url(href)
        resolved = button_or_link.evaluate(
            """
            (el) => {
              const anchor = el.closest("a[href]");
              return anchor?.href || el.dataset?.url || el.getAttribute("data-url") || "";
            }
            """
        )
        return canonical_url(str(resolved)) if resolved else candidate.url

    def _extract_visible_candidates(
        self,
        search_url: str,
        *,
        max_posted_age_days: int | None = None,
    ) -> list[JobCandidate]:
        payload = self.active_page.evaluate(
            """
            () => {
              const anchors = [...document.querySelectorAll("a[href]")];
              const picked = [];
              for (const anchor of anchors) {
                const href = anchor.href || "";
                const text = (anchor.innerText || anchor.textContent || "").trim();
                if (!href || !text) continue;
                let parsed;
                try {
                  parsed = new URL(href, window.location.href);
                } catch {
                  continue;
                }
                const isNaukriHost = /(^|\\.)naukri\\.com$/i.test(parsed.hostname);
                const isJobListing =
                  parsed.pathname.includes("/job-listings-") ||
                  parsed.pathname.includes("/job-listing-");
                if (!isNaukriHost || !isJobListing) continue;
                const card = anchor.closest("article, li, section, div") || anchor.parentElement;
                const cardText = (card?.innerText || "").trim();
                if (!cardText) continue;
                picked.push({
                  href,
                  title: text,
                  cardText,
                  cardHtml: card?.outerHTML || "",
                });
              }
              return picked.slice(0, 160);
            }
            """
        )

        candidates: list[JobCandidate] = []
        for item in payload:
            raw_text = "\n".join(
                normalized_line
                for normalized_line in (
                    normalize_space(line) for line in str(item.get("cardText", "")).splitlines()
                )
                if normalized_line
            )
            if max_posted_age_days is not None and not self._is_recent_posting(
                raw_text,
                max_days=max_posted_age_days,
            ):
                logger.info(
                    "Skipped older visible posting search_url=%s max_days=%s title=%s",
                    search_url,
                    max_posted_age_days,
                    normalize_space(str(item.get("title", ""))),
                )
                continue
            title = normalize_space(str(item.get("title", "")))
            url = canonical_url(str(item.get("href", "")))
            if not title or not url:
                continue
            company = self._guess_company(raw_text, title, url)
            snippet = normalize_space(raw_text)[:500]
            experience_text = self._guess_experience(raw_text, url)
            location_text = self._guess_location(raw_text)
            job_id = self._extract_job_id(url)
            stable_key = stable_job_key(job_id, url, title, company)
            candidates.append(
                JobCandidate(
                    stable_key=stable_key,
                    job_id=job_id,
                    url=url,
                    title=title,
                    company=company,
                    snippet=snippet,
                    raw_text=raw_text,
                    experience_text=experience_text,
                    location_text=location_text,
                    source_path=SourcePath.UNKNOWN,
                    search_url=search_url,
                )
            )
        return candidates

    @staticmethod
    def _with_job_age_filter(url: str, max_posted_age_days: int) -> str:
        parsed = urlsplit(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["jobAge"] = str(max_posted_age_days)
        return urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(query, doseq=True),
                parsed.fragment,
            )
        )

    @staticmethod
    def _is_recent_posting(raw_text: str, *, max_days: int) -> bool:
        normalized = normalize_space(raw_text).lower()
        if not normalized:
            return False
        immediate_markers = [
            "just now",
            "few hours ago",
            "hour ago",
            "hours ago",
            "minute ago",
            "minutes ago",
            "today",
            "yesterday",
        ]
        if any(marker in normalized for marker in immediate_markers):
            return True

        day_match = re.search(r"(\d+)\+?\s+days?\s+ago", normalized)
        if day_match:
            return int(day_match.group(1)) <= max_days

        week_match = re.search(r"(\d+)\+?\s+weeks?\s+ago", normalized)
        if week_match:
            return int(week_match.group(1)) * 7 <= max_days

        month_match = re.search(r"(\d+)\+?\s+months?\s+ago", normalized)
        if month_match:
            return False

        return False

    def _goto_next_results_page(self) -> bool:
        candidates = [
            self.active_page.get_by_text(re.compile(r"^next$", re.I)),
            self.active_page.locator("a[rel='next']"),
            self.active_page.locator("button[aria-label*='Next' i]"),
        ]
        for locator in candidates:
            if locator.count():
                try:
                    locator.first.click()
                    self.active_page.wait_for_timeout(1800)
                    return True
                except TimeoutError:
                    continue
        return False

    def _find_apply_button(self) -> Locator | None:
        patterns = [
            self.active_page.get_by_text(re.compile(r"^apply$", re.I)),
            self.active_page.locator("button").filter(has_text=re.compile(r"^apply$", re.I)),
        ]
        for locator in patterns:
            if locator.count():
                return locator.first
        return None

    def _find_submit_button(self) -> Locator | None:
        scopes = [
            self.active_page.locator("[role='dialog']").filter(visible=True),
            self.active_page.locator(".modal, .drawer, form").filter(visible=True),
        ]
        scoped_patterns = [
            re.compile(r"submit", re.I),
            re.compile(r"save", re.I),
            re.compile(r"send application", re.I),
            re.compile(r"^apply$", re.I),
        ]
        for scope in scopes:
            for scope_index in range(scope.count()):
                scoped = scope.nth(scope_index)
                for pattern in scoped_patterns:
                    locator = scoped.locator("button").filter(has_text=pattern, visible=True)
                    if locator.count():
                        return locator.last

        fallback_patterns = [
            re.compile(r"submit", re.I),
            re.compile(r"send application", re.I),
        ]
        for pattern in fallback_patterns:
            locator = self.active_page.locator("button").filter(has_text=pattern, visible=True)
            if locator.count():
                return locator.last
        return None

    def _application_confirmation_visible(self) -> bool:
        return self._visible_text_exists(r"applied|application submitted|already applied")

    def _click_with_overlay_recovery(
        self,
        locator: Locator,
        *,
        action_label: str,
        candidate: JobCandidate,
    ) -> str | None:
        try:
            locator.click(timeout=7_000)
            return None
        except TimeoutError:
            if not self._chatbot_overlay_visible():
                logger.warning(
                    "%s click timed out stable_key=%s without known overlay",
                    action_label,
                    candidate.stable_key,
                )
                return f"{action_label} click timed out before Playwright could safely click it."

            logger.warning(
                "%s click blocked by chatbot overlay stable_key=%s",
                action_label,
                candidate.stable_key,
            )
            print()
            print(f"Naukri's chatbot overlay is blocking the {action_label} button.")
            decision = input(
                "Close that overlay in the browser, then press Enter to retry. Type s to stop this job: "
            ).strip().lower()
            if decision == "s":
                return f"{action_label} was blocked by Naukri's chatbot overlay."

            try:
                locator.click(timeout=7_000)
                logger.info(
                    "%s click succeeded after chatbot overlay recovery stable_key=%s",
                    action_label,
                    candidate.stable_key,
                )
                return None
            except TimeoutError:
                logger.warning(
                    "%s retry timed out after chatbot overlay recovery stable_key=%s",
                    action_label,
                    candidate.stable_key,
                )
                return f"{action_label} is still blocked after the chatbot overlay retry."

    def _chatbot_overlay_visible(self) -> bool:
        overlays = self.active_page.locator(
            ".chatbot_Overlay.show, [class*='chatbot_Overlay'].show"
        ).filter(visible=True)
        return overlays.count() > 0

    def _complete_chatbot_questionnaire(
        self,
        answer_memory: AnswerMemory,
        candidate: JobCandidate,
    ) -> ApplicationResult | None:
        if not self._wait_for_chatbot_to_open():
            logger.info("Chatbot not detected after apply wait stable_key=%s", candidate.stable_key)
            self._log_dom_snapshot("chatbot_not_detected_after_apply", candidate)
            return None

        logger.info("Chatbot questionnaire opened stable_key=%s", candidate.stable_key)
        idle_cycles = 0
        for turn in range(20):
            if not self._chatbot_container_visible():
                logger.info("Chatbot closed after questionnaire stable_key=%s", candidate.stable_key)
                return ApplicationResult(
                    submitted=True,
                    message="Chatbot questionnaire completed and closed itself.",
                )
            if self._application_confirmation_visible():
                logger.info("Application confirmation detected during chatbot stable_key=%s", candidate.stable_key)
                return ApplicationResult(
                    submitted=True,
                    message="Application submission was confirmed while the chatbot was active.",
                )
            if self._chatbot_completion_visible():
                return self._wait_for_completed_chatbot_to_close(candidate)

            self.active_page.wait_for_timeout(2_000)
            if not self._chatbot_container_visible():
                logger.info("Chatbot closed during response wait stable_key=%s", candidate.stable_key)
                return ApplicationResult(
                    submitted=True,
                    message="Chatbot questionnaire completed and closed itself.",
                )
            if self._chatbot_completion_visible():
                return self._wait_for_completed_chatbot_to_close(candidate)

            question = self._latest_chatbot_question()
            options = self._chatbot_option_labels()
            text_input = self._chatbot_text_input()

            if not question:
                idle_cycles += 1
                if idle_cycles >= 4:
                    logger.warning("Chatbot active without readable question stable_key=%s", candidate.stable_key)
                    self._log_dom_snapshot("chatbot_without_readable_question", candidate)
                    return ApplicationResult(
                        submitted=False,
                        message="Chatbot opened, but no readable question was detected.",
                    )
                continue

            if text_input is not None:
                answer = self._resolve_answer_value(
                    question=question,
                    answer_type=AnswerType.TEXT,
                    choices=[],
                    answer_memory=answer_memory,
                )
                if answer is None:
                    logger.warning("No chatbot text answer provided stable_key=%s question=%s", candidate.stable_key, question)
                    return ApplicationResult(
                        submitted=False,
                        message="Chatbot question was left unanswered.",
                    )
                self._fill_chatbot_text_input(text_input, str(answer))
                if not self._submit_chatbot_text_input(text_input):
                    logger.warning(
                        "Chatbot text answer could not be saved stable_key=%s",
                        candidate.stable_key,
                    )
                    self._log_dom_snapshot("chatbot_text_save_missing", candidate)
                    return ApplicationResult(
                        submitted=False,
                        message="Chatbot text answer was entered, but Save could not be clicked.",
                    )
                logger.info(
                    "Answered chatbot text question stable_key=%s turn=%s",
                    candidate.stable_key,
                    turn + 1,
                )
                idle_cycles = 0
                self.active_page.wait_for_timeout(2_000)
                continue

            if options:
                answer = self._resolve_answer_value(
                    question=question,
                    answer_type=AnswerType.SINGLE_SELECT,
                    choices=options,
                    answer_memory=answer_memory,
                )
                if answer is None:
                    logger.warning("No chatbot option answer provided stable_key=%s question=%s", candidate.stable_key, question)
                    return ApplicationResult(
                        submitted=False,
                        message="Chatbot question was left unanswered.",
                    )
                option_requires_save = self._chatbot_option_requires_save()
                if not self._click_chatbot_option(str(answer)):
                    logger.warning(
                        "Chatbot option answer did not match visible options stable_key=%s answer=%s",
                        candidate.stable_key,
                        answer,
                    )
                    self._log_dom_snapshot("chatbot_option_answer_mismatch", candidate)
                    return ApplicationResult(
                        submitted=False,
                        message=f"Chatbot answer `{answer}` did not match the visible options.",
                    )
                if option_requires_save and not self._save_chatbot_response():
                    logger.warning(
                        "Chatbot option answer could not be saved stable_key=%s answer=%s",
                        candidate.stable_key,
                        answer,
                    )
                    self._log_dom_snapshot("chatbot_option_save_missing", candidate)
                    return ApplicationResult(
                        submitted=False,
                        message="Chatbot option was selected, but Save could not be clicked.",
                    )
                logger.info(
                    "Answered chatbot option question stable_key=%s turn=%s",
                    candidate.stable_key,
                    turn + 1,
                )
                idle_cycles = 0
                self.active_page.wait_for_timeout(2_000)
                continue

            idle_cycles += 1
            if idle_cycles >= 4:
                logger.warning(
                    "Chatbot question had no answer control stable_key=%s question=%s",
                    candidate.stable_key,
                    question,
                )
                self._log_dom_snapshot("chatbot_question_without_answer_control", candidate)
                return ApplicationResult(
                    submitted=False,
                    message="Chatbot question appeared without a detectable answer control.",
                )

        logger.warning("Chatbot questionnaire exceeded turn limit stable_key=%s", candidate.stable_key)
        self._log_dom_snapshot("chatbot_turn_limit_exceeded", candidate)
        return ApplicationResult(
            submitted=False,
            message="Chatbot questionnaire did not finish within 20 turns.",
        )

    def _wait_for_chatbot_to_open(self, *, timeout_ms: int = 15_000) -> bool:
        waited = 0
        while waited <= timeout_ms:
            if self._chatbot_container_visible():
                return True
            self.active_page.wait_for_timeout(400)
            waited += 400
        return False

    def _chatbot_completion_visible(self) -> bool:
        containers = self._chatbot_container()
        if not containers.count():
            return False
        completion = containers.last.locator(".botMsg, .botItem").filter(
            has_text=re.compile(
                r"thank you for your responses|thank you for your response|responses have been recorded|application submitted",
                re.I,
            )
        )
        return completion.count() > 0

    def _wait_for_completed_chatbot_to_close(
        self,
        candidate: JobCandidate,
        *,
        timeout_ms: int = 15_000,
    ) -> ApplicationResult:
        logger.info("Chatbot completion message detected stable_key=%s", candidate.stable_key)
        waited = 0
        while waited <= timeout_ms:
            if not self._chatbot_container_visible():
                logger.info("Completed chatbot drawer closed stable_key=%s", candidate.stable_key)
                return ApplicationResult(
                    submitted=True,
                    message="Chatbot showed its completion response and closed itself.",
                )
            self.active_page.wait_for_timeout(2_000)
            waited += 2_000
        logger.warning(
            "Chatbot completion message appeared but drawer stayed open stable_key=%s",
            candidate.stable_key,
        )
        self._log_dom_snapshot("chatbot_completion_drawer_still_open", candidate)
        return ApplicationResult(
            submitted=False,
            message="Chatbot showed its completion response, but the drawer did not close on its own.",
        )

    def _chatbot_container_visible(self) -> bool:
        containers = self._chatbot_container()
        if not containers.count():
            return False
        visible_surfaces = containers.last.locator(
            ".chatbot_Drawer, .chatbot_MessageContainer, .footerWrapper, .chatbot_Overlay.show"
        ).filter(visible=True)
        if visible_surfaces.count():
            return True
        return containers.last.is_visible()

    def _chatbot_container(self) -> Locator:
        return self.active_page.locator(
            "._chatBotContainer, [class*='_chatBotContainer'], [id*='ChatbotContainer']"
        )

    def _latest_chatbot_question(self) -> str:
        containers = self._chatbot_container()
        if not containers.count():
            return ""
        bot_messages = containers.last.locator(".botItem .botMsg, .botMsg")
        if bot_messages.count():
            spans = bot_messages.last.locator("span")
            if spans.count():
                return normalize_space(" ".join(spans.all_inner_texts()))
            return normalize_space(bot_messages.last.inner_text())
        raw = containers.last.evaluate(
            """
            (container) => {
              const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
              const lines = [];
              while (walker.nextNode()) {
                const node = walker.currentNode;
                const parent = node.parentElement;
                if (!parent || parent.closest("button, [role='button'], label")) continue;
                const value = (node.textContent || "").trim();
                if (value) lines.push(value);
              }
              return lines
                .map((line) => line.trim())
                .filter(Boolean)
                .filter((line) => !/^(send|submit|close|skip|×|x)$/i.test(line))
                .filter((line) => !/^\\.+$/.test(line))
                .at(-1) || "";
            }
            """
        )
        return normalize_space(str(raw or ""))

    def _chatbot_option_labels(self) -> list[str]:
        containers = self._chatbot_container()
        if not containers.count():
            return []
        radio_labels = containers.last.locator(
            ".singleselect-radiobutton label.ssrc__label, label.ssrc__label"
        )
        labels: list[str] = []
        for index in range(radio_labels.count()):
            label = normalize_space(radio_labels.nth(index).inner_text())
            if label:
                labels.append(label)
        if labels:
            return list(dict.fromkeys(labels))
        chip_labels = containers.last.locator(
            ".chatbot_Chip span, .chatbot_Chip, .chipItem span, .chipItem"
        ).filter(visible=True)
        chip_values: list[str] = []
        for index in range(chip_labels.count()):
            label = normalize_space(chip_labels.nth(index).inner_text())
            if label:
                chip_values.append(label)
        if chip_values:
            return list(dict.fromkeys(chip_values))
        labels = containers.last.evaluate(
            """
            (container) => {
              const elements = [...container.querySelectorAll("button, [role='button']")];
              return elements
                .filter((element) => {
                  const rect = element.getBoundingClientRect();
                  const style = window.getComputedStyle(element);
                  return rect.width > 0 && rect.height > 0 && style.visibility !== "hidden";
                })
                .map((element) => (element.innerText || element.textContent || "").trim())
                .filter(Boolean)
                .filter((label) => !/^(send|submit|close|skip|×|x)$/i.test(label))
                .filter((label) => label.length <= 120);
            }
            """
        )
        return list(dict.fromkeys(normalize_space(str(label)) for label in labels if normalize_space(str(label))))

    def _click_chatbot_option(self, answer: str) -> bool:
        target = normalize_space(answer).lower()
        containers = self._chatbot_container()
        if not containers.count():
            return False
        radio_labels = containers.last.locator(
            ".singleselect-radiobutton label.ssrc__label, label.ssrc__label"
        ).filter(visible=True)
        for index in range(radio_labels.count()):
            label = radio_labels.nth(index)
            label_text = normalize_space(label.inner_text())
            if label_text.lower() != target:
                continue
            label.click(timeout=7_000)
            return True
        chips = containers.last.locator(
            ".chatbot_Chip, .chipItem"
        ).filter(visible=True)
        for index in range(chips.count()):
            chip = chips.nth(index)
            chip_text = normalize_space(chip.inner_text())
            if chip_text.lower() != target:
                continue
            chip.click(timeout=7_000)
            return True
        choices = containers.last.locator("button, [role='button']").filter(visible=True)
        for index in range(choices.count()):
            choice = choices.nth(index)
            label = normalize_space(choice.inner_text())
            if label.lower() != target:
                continue
            choice.click(timeout=7_000)
            return True
        return False

    def _chatbot_option_requires_save(self) -> bool:
        containers = self._chatbot_container()
        if not containers.count():
            return True
        save_container = containers.last.locator(
            ".sendMsgbtn_container, [id*='sendMsgbtn_container']"
        )
        if save_container.count():
            class_name = save_container.last.get_attribute("class") or ""
            if "visibility-hidden" in class_name or "d-none" in class_name:
                return False
            send_class = save_container.last.locator(".send").first.get_attribute("class") or ""
            if "disabled" in send_class and self._chatbot_chip_options_visible():
                return False
            visible = save_container.last.filter(visible=True)
            if visible.count():
                return True
        chips = containers.last.locator(".chatbot_Chip, .chipItem").filter(visible=True)
        return not bool(chips.count())

    def _chatbot_chip_options_visible(self) -> bool:
        containers = self._chatbot_container()
        if not containers.count():
            return False
        chips = containers.last.locator(".chatbot_Chip, .chipItem").filter(visible=True)
        return chips.count() > 0

    def _chatbot_text_input(self) -> Locator | None:
        containers = self._chatbot_container()
        if not containers.count():
            return None
        contenteditable = containers.last.locator(
            ".footerInputBoxWrapper [contenteditable='true'], [contenteditable='true'].textArea"
        ).filter(visible=True)
        if contenteditable.count():
            return contenteditable.last
        inputs = containers.last.locator(
            "textarea, input:not([type='hidden']):not([type='checkbox']):not([type='radio'])"
        ).filter(visible=True)
        return inputs.last if inputs.count() else None

    def _fill_chatbot_text_input(self, text_input: Locator, answer: str) -> None:
        if (text_input.get_attribute("contenteditable") or "").lower() == "true":
            text_input.click(timeout=7_000)
            text_input.evaluate(
                """
                (element, value) => {
                  element.textContent = "";
                  element.textContent = value;
                  element.dispatchEvent(new InputEvent("input", {
                    bubbles: true,
                    inputType: "insertText",
                    data: value,
                  }));
                }
                """,
                answer,
            )
            return
        text_input.fill(answer)

    def _submit_chatbot_text_input(self, text_input: Locator) -> bool:
        if self._save_chatbot_response():
            return True
        text_input.press("Enter")
        return True

    def _save_chatbot_response(self) -> bool:
        containers = self._chatbot_container()
        if containers.count():
            send_candidates = [
                containers.last.get_by_text(re.compile(r"^save$", re.I)),
                containers.last.locator(".sendMsg"),
                containers.last.locator("[id*='sendMsg'], .send"),
                containers.last.get_by_text(re.compile(r"^send$", re.I)),
                containers.last.locator("button[aria-label*='send' i], [role='button'][aria-label*='send' i]"),
                containers.last.locator("button[class*='send' i], [role='button'][class*='send' i]"),
            ]
            for locator in send_candidates:
                visible = locator.filter(visible=True)
                if visible.count():
                    visible.last.click(timeout=7_000)
                    return True
        return False

    def _log_dom_snapshot(self, label: str, candidate: JobCandidate | None = None) -> None:
        try:
            snapshot = self.active_page.evaluate(
                """
                () => {
                  const roots = [
                    document.querySelector("._chatBotContainer"),
                    document.querySelector("[id*='ChatbotContainer']"),
                    document.querySelector("[role='dialog']"),
                    document.querySelector(".modal"),
                    document.querySelector(".drawer"),
                  ].filter(Boolean);
                  const html = roots.length
                    ? roots.map((root) => root.outerHTML).join("\\n\\n")
                    : document.body?.outerHTML || "";
                  return html.replace(/\\s+/g, " ").trim().slice(0, 12000);
                }
                """
            )
        except Exception as exc:
            logger.warning(
                "DOM snapshot failed label=%s stable_key=%s error=%s",
                label,
                candidate.stable_key if candidate else "",
                exc,
            )
            return

        logger.info(
            "DOM_SNAPSHOT label=%s stable_key=%s html=%s",
            label,
            candidate.stable_key if candidate else "",
            snapshot,
        )

    def _fill_visible_questionnaire(self, answer_memory: AnswerMemory) -> None:
        controls = self.active_page.locator("textarea, input:not([type='hidden']), select")
        for index in range(controls.count()):
            control = controls.nth(index)
            try:
                if not control.is_visible():
                    continue
                if control.evaluate("(el) => el.disabled"):
                    continue
                if control.input_value():
                    continue
            except Exception:
                continue

            question = self._label_for_control(control)
            if not question:
                continue
            answer, answer_type = self._resolve_answer(question, control, answer_memory)
            if answer is None:
                continue
            self._fill_control(control, answer, answer_type)

    def _resolve_answer(self, question: str, control: Locator, answer_memory: AnswerMemory):
        answer_type = self._infer_answer_type(control)
        choices = self._choices_for_control(control)
        answer = self._resolve_answer_value(
            question=question,
            answer_type=answer_type,
            choices=choices,
            answer_memory=answer_memory,
        )
        return answer, answer_type

    def _resolve_answer_value(
        self,
        *,
        question: str,
        answer_type: AnswerType,
        choices: list[str],
        answer_memory: AnswerMemory,
    ):
        exact = answer_memory.exact_match(question)
        if exact:
            answer_memory.touch(exact)
            return exact.answer

        fuzzy = answer_memory.best_fuzzy_match(question)
        if fuzzy:
            print()
            print(f"Stored similar question: {fuzzy.answer.raw_questions[0]}")
            print(f"Current question: {question}")
            print(f"Suggested answer: {fuzzy.answer.answer}")
            # use_saved = input("Use this saved answer? [y/N]: ").strip().lower()
            use_saved = "y"
            if use_saved == "y":
                updated = answer_memory.touch(fuzzy.answer)
                return updated.answer

        print()
        print(f"Required question: {question}")
        if choices:
            print(f"Choices: {', '.join(choices)}")
        answer = input("Answer: ").strip()
        if not answer:
            return None
        remembered = answer_memory.remember(
            question=question,
            answer_value=answer,
            answer_type=answer_type,
            choices=choices,
        )
        return remembered.answer

    def _fill_control(self, control: Locator, answer, answer_type: AnswerType) -> None:
        if answer_type == AnswerType.SINGLE_SELECT:
            control.select_option(label=str(answer))
            return
        input_type = control.get_attribute("type") or ""
        if input_type in {"checkbox", "radio"}:
            if str(answer).strip().lower() in {"yes", "true", "1", "y"}:
                control.check()
            return
        control.fill(str(answer))

    def _label_for_control(self, control: Locator) -> str:
        label = control.evaluate(
            """
            (el) => {
              const id = el.getAttribute("id");
              if (id) {
                const direct = document.querySelector(`label[for="${CSS.escape(id)}"]`);
                if (direct) return direct.innerText || direct.textContent || "";
              }
              const wrapper = el.closest("label, .form-group, .field, div");
              if (wrapper) {
                const text = (wrapper.innerText || wrapper.textContent || "").trim();
                return text.split("\\n")[0] || "";
              }
              return el.getAttribute("placeholder") || el.getAttribute("aria-label") || "";
            }
            """
        )
        return normalize_space(str(label or ""))

    def _infer_answer_type(self, control: Locator) -> AnswerType:
        tag_name = control.evaluate("(el) => el.tagName.toLowerCase()")
        input_type = (control.get_attribute("type") or "").lower()
        if tag_name == "select":
            return AnswerType.SINGLE_SELECT
        if input_type == "number":
            return AnswerType.NUMERIC
        if input_type in {"radio", "checkbox"}:
            return AnswerType.YES_NO
        return AnswerType.TEXT

    def _choices_for_control(self, control: Locator) -> list[str]:
        tag_name = control.evaluate("(el) => el.tagName.toLowerCase()")
        if tag_name != "select":
            return []
        options = control.locator("option")
        values: list[str] = []
        for index in range(options.count()):
            label = normalize_space(options.nth(index).inner_text())
            if label:
                values.append(label)
        return values

    def _visible_text_exists(self, pattern: str) -> bool:
        locator = self.active_page.get_by_text(re.compile(pattern, re.I)).filter(visible=True)
        return locator.count() > 0

    @staticmethod
    def _guess_company(raw_text: str, title: str, url: str = "") -> str:
        lines = [normalize_space(line) for line in raw_text.splitlines() if normalize_space(line)]
        for line in lines:
            if line != title and len(line) <= 120:
                return line
        return NaukriBrowser._company_from_job_url(url, title)

    @staticmethod
    def _company_from_job_url(url: str, title: str) -> str:
        match = re.search(r"/job-listings-(?P<slug>.+)-(?P<job_id>\d+)(?:[/?#]|$)", url, re.I)
        if not match:
            return ""

        slug = match.group("slug")
        experience = re.search(r"-(?:\d+)-to-(?:\d+)-years(?:-|$)", slug, re.I)
        head = slug[: experience.start()] if experience else slug
        title_slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        if not title_slug or not head.lower().startswith(f"{title_slug}-"):
            return ""

        company_slug = head[len(title_slug) + 1 :].strip("-")
        if not company_slug:
            return ""
        return " ".join(part.capitalize() for part in company_slug.split("-") if part)

    @staticmethod
    def _guess_experience(raw_text: str, url: str = "") -> str:
        match = re.search(r"\b\d+(?:\.\d+)?\s*(?:-|to)\s*\d+(?:\.\d+)?\s*(?:years?|yrs?)\b", raw_text, re.I)
        if match:
            return match.group(0)
        match = re.search(r"\b\d+(?:\.\d+)?\s*\+?\s*(?:years?|yrs?)\b", raw_text, re.I)
        if match:
            return match.group(0)
        url_match = re.search(r"(?P<low>\d+)-to-(?P<high>\d+)-years", url, re.I)
        if url_match:
            return f"{url_match.group('low')}-{url_match.group('high')} years"
        return ""

    @staticmethod
    def _guess_location(raw_text: str) -> str:
        known_fragments = ["Bengaluru", "Bangalore", "Hyderabad", "Pune", "Mumbai", "Chennai", "Noida", "Gurugram", "Delhi"]
        for fragment in known_fragments:
            if fragment.lower() in raw_text.lower():
                return fragment
        return ""

    @staticmethod
    def _extract_job_id(url: str) -> str | None:
        patterns: Iterable[re.Pattern[str]] = [
            re.compile(r"job-listings-.+-(?P<job_id>\d+)(?:[/?#]|$)", re.I),
            re.compile(r"[?&]jobId=(?P<job_id>\d+)", re.I),
        ]
        for pattern in patterns:
            match = pattern.search(url)
            if match:
                return match.group("job_id")
        return None
