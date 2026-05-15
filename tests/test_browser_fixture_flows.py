from pathlib import Path

from playwright.sync_api import TimeoutError

from naukri_assistant.answers import AnswerMemory
from naukri_assistant.browser import NaukriBrowser
from naukri_assistant.models import AnswerType, JobCandidate


def test_extract_visible_candidate_from_fixture(tmp_path: Path) -> None:
    html = """
    <article>
      <a href="https://www.naukri.com/job-listings-software-engineer-acme-123456">Software Engineer</a>
      <div>Acme Technologies</div>
      <div>Python, FastAPI, SQL</div>
      <div>1-3 years</div>
      <div>Bengaluru</div>
    </article>
    """
    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        candidates = browser._extract_visible_candidates("https://www.naukri.com/search?k=software")
    assert len(candidates) == 1
    assert candidates[0].title == "Software Engineer"
    assert candidates[0].job_id == "123456"
    assert candidates[0].company == "Acme Technologies"
    assert candidates[0].location_text == "Bengaluru"


def test_extract_visible_candidates_ignores_non_job_links(tmp_path: Path) -> None:
    html = """
    <a href="https://www.shiksha.com/engineering-chp">Engineering</a>
    <a href="https://my.naukri.com/Inbox/viewRecruiterMails">Software Engineer invite</a>
    <article>
      <a href="https://www.naukri.com/job-listings-software-engineer-acme-123456">Software Engineer</a>
    </article>
    """
    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        candidates = browser._extract_visible_candidates("https://www.naukri.com/search?k=software")
    assert [candidate.job_id for candidate in candidates] == ["123456"]


def test_extract_visible_candidates_skips_jobs_older_than_one_week(tmp_path: Path) -> None:
    html = """
    <article>
      <a href="https://www.naukri.com/job-listings-software-engineer-acme-123456">Software Engineer</a>
      <div>Acme Technologies</div>
      <div>Posted 2 days ago</div>
    </article>
    <article>
      <a href="https://www.naukri.com/job-listings-backend-engineer-beta-987654">Backend Engineer</a>
      <div>Beta Labs</div>
      <div>Posted 12 days ago</div>
    </article>
    """
    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        candidates = browser._extract_visible_candidates(
            "https://www.naukri.com/search?k=software",
            max_posted_age_days=7,
        )
    assert [candidate.job_id for candidate in candidates] == ["123456"]


def test_company_and_experience_fall_back_to_job_url() -> None:
    url = "https://www.naukri.com/job-listings-Custom-Software-Engineer-Accenture-2-to-5-years-110526917119"
    assert NaukriBrowser._guess_company("", "Custom Software Engineer", url) == "Accenture"
    assert NaukriBrowser._guess_experience("", url) == "2-5 years"


def test_fill_visible_questionnaire_with_saved_exact_answer(tmp_path: Path) -> None:
    html = """
    <form>
      <label for="notice">What is your notice period?</label>
      <input id="notice" type="text" />
    </form>
    """
    memory = AnswerMemory()
    memory.remember(
        question="What is your notice period?",
        answer_value="30 days",
        answer_type=AnswerType.TEXT,
    )
    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        browser._fill_visible_questionnaire(memory)
        value = browser.active_page.locator("#notice").input_value()
    assert value == "30 days"


def test_fill_visible_select_question_with_saved_answer(tmp_path: Path) -> None:
    html = """
    <form>
      <label for="relocate">Are you open to relocation?</label>
      <select id="relocate">
        <option value="">Choose</option>
        <option>Yes</option>
        <option>No</option>
      </select>
    </form>
    """
    memory = AnswerMemory()
    memory.remember(
        question="Are you open to relocation?",
        answer_value="Yes",
        answer_type=AnswerType.SINGLE_SELECT,
        choices=["Yes", "No"],
    )
    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        browser._fill_visible_questionnaire(memory)
        value = browser.active_page.locator("#relocate").input_value()
    assert value == "Yes"


def test_external_redirect_text_detection(tmp_path: Path) -> None:
    html = "<button>Apply on Company Website</button>"
    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        assert browser._visible_text_exists(r"apply on company website") is True


def test_page_level_apply_button_is_not_reused_as_final_submit(tmp_path: Path) -> None:
    html = "<button class='apply-btn'>Apply</button>"
    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        assert browser._find_submit_button() is None


def test_dialog_apply_button_can_be_final_submit(tmp_path: Path) -> None:
    html = "<div role='dialog'><button>Apply</button></div>"
    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        assert browser._find_submit_button() is not None


def test_chatbot_overlay_click_failure_stops_current_job_cleanly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    html = """
    <style>
      .chatbot_Overlay.show { position: fixed; inset: 0; width: 100px; height: 100px; }
    </style>
    <button id="submit">Submit</button>
    <div class="chatbot_Overlay show"></div>
    """
    candidate = JobCandidate(
        stable_key="job:overlay",
        url="https://www.naukri.com/job-listings-software-engineer-acme-123",
        title="Software Engineer",
    )

    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        locator = browser.active_page.locator("#submit")

        def raise_timeout(*args, **kwargs):
            raise TimeoutError("overlay blocks pointer events")

        monkeypatch.setattr(type(locator), "click", raise_timeout)
        monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "s")

        result = browser._click_with_overlay_recovery(
            locator,
            action_label="final Submit",
            candidate=candidate,
        )

    assert result == "final Submit was blocked by Naukri's chatbot overlay."


def test_chatbot_option_question_uses_saved_answer_until_container_closes(tmp_path: Path) -> None:
    html = """
    <div class="_chatBotContainer" id="_demoChatbotContainer">
      <ul class="list">
        <li class="botItem chatbot_ListItem">
          <div class="botMsg msg"><div><span>How many years of experience do you have as Frontend Developer ?</span></div></div>
        </li>
      </ul>
      <div class="singleselect-radiobutton">
        <div class="ssrc__radio-btn-container">
          <input type="radio" id="No experience" name="radio-button" value="No experience">
          <label for="No experience" class="ssrc__label">No experience</label>
        </div>
        <div class="ssrc__radio-btn-container">
          <input type="radio" id="1-3 years" name="radio-button" value="1-3 years">
          <label for="1-3 years" class="ssrc__label">1-3 years</label>
        </div>
      </div>
      <div class="sendMsgbtn_container">
        <div class="send">
          <div class="sendMsg" tabindex="0" onclick="document.getElementById('_demoChatbotContainer').remove()">Save</div>
        </div>
      </div>
    </div>
    """
    memory = AnswerMemory()
    memory.remember(
        question="How many years of experience do you have as Frontend Developer ?",
        answer_value="1-3 years",
        answer_type=AnswerType.SINGLE_SELECT,
        choices=["No experience", "1-3 years"],
    )
    candidate = JobCandidate(
        stable_key="job:chatbot",
        url="https://www.naukri.com/job-listings-software-engineer-acme-123",
        title="Software Engineer",
    )

    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        result = browser._complete_chatbot_questionnaire(memory, candidate)

    assert result is not None
    assert result.submitted is True
    assert "closed itself" in result.message


def test_chatbot_text_question_uses_contenteditable_and_save(tmp_path: Path) -> None:
    html = """
    <div class="_chatBotContainer" id="_textChatbotContainer">
      <ul class="list">
        <li class="botItem chatbot_ListItem">
          <div class="botMsg msg"><div><span>What is your current notice period?</span></div></div>
        </li>
      </ul>
      <div class="footerInputBoxWrapper">
        <div class="textArea" contenteditable="true" data-placeholder="Type message here...">Old value</div>
      </div>
      <div class="sendMsgbtn_container">
        <div class="send">
          <div class="sendMsg" tabindex="0" onclick="document.getElementById('_textChatbotContainer').remove()">Save</div>
        </div>
      </div>
    </div>
    """
    memory = AnswerMemory()
    memory.remember(
        question="What is your current notice period?",
        answer_value="30 days",
        answer_type=AnswerType.TEXT,
    )
    candidate = JobCandidate(
        stable_key="job:text-chatbot",
        url="https://www.naukri.com/job-listings-software-engineer-acme-456",
        title="Software Engineer",
    )

    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        text_input = browser._chatbot_text_input()
        assert text_input is not None
        browser._fill_chatbot_text_input(text_input, "30 days")
        assert text_input.inner_text() == "30 days"
        result = browser._complete_chatbot_questionnaire(memory, candidate)

    assert result is not None
    assert result.submitted is True
    assert "closed itself" in result.message


def test_chatbot_completion_message_waits_for_drawer_to_close(tmp_path: Path) -> None:
    html = """
    <div class="_chatBotContainer" id="_completionChatbotContainer">
      <ul class="list">
        <li class="botItem chatbot_ListItem">
          <div class="botMsg msg"><div><span>Thank you for your responses.</span></div></div>
        </li>
      </ul>
    </div>
    <script>
      setTimeout(() => document.getElementById("_completionChatbotContainer").remove(), 100);
    </script>
    """
    candidate = JobCandidate(
        stable_key="job:completion-chatbot",
        url="https://www.naukri.com/job-listings-software-engineer-acme-789",
        title="Software Engineer",
    )

    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        result = browser._complete_chatbot_questionnaire(AnswerMemory(), candidate)

    assert result is not None
    assert result.submitted is True
    assert "completion response" in result.message


def test_chatbot_detection_uses_visible_drawer_even_if_wrapper_is_zero_size(tmp_path: Path) -> None:
    html = """
    <style>
      ._chatBotContainer { position: relative; width: 0; height: 0; }
      .chatbot_Drawer { position: absolute; width: 320px; height: 220px; }
      .chatbot_MessageContainer { width: 320px; height: 180px; }
    </style>
    <div class="_chatBotContainer" id="_drawerChatbotContainer">
      <div class="chatbot_Drawer chatbot_right">
        <div class="chatbot_MessageContainer">
          <ul class="list">
            <li class="botItem chatbot_ListItem">
              <div class="botMsg msg"><div><span>What is your current location ?</span></div></div>
            </li>
          </ul>
        </div>
      </div>
    </div>
    """
    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        assert browser._chatbot_container_visible() is True


def test_chatbot_chip_options_are_self_submitting(tmp_path: Path) -> None:
    html = """
    <div class="_chatBotContainer" id="_chipChatbotContainer">
      <div class="chatbot_Drawer chatbot_right">
        <div class="chatbot_MessageContainer">
          <ul class="list">
            <li class="botItem chatbot_ListItem">
              <div class="botMsg msg">
                <div><span>Are you on a career break?</span></div>
              </div>
            </li>
          </ul>
          <div class="chipsContainer">
            <div class="chatbot_Chips chatbot_ChipsInRow">
              <div class="chatbot_Chip chipInRow chipItem"><span>Yes</span></div>
              <div class="chatbot_Chip chipInRow chipItem" onclick="document.getElementById('_chipChatbotContainer').remove()"><span>No</span></div>
            </div>
          </div>
        </div>
        <div class="sendMsgbtn_container visibility-hidden">
          <div class="send disabled"><div class="sendMsg" tabindex="0">Save</div></div>
        </div>
      </div>
    </div>
    """
    memory = AnswerMemory()
    memory.remember(
        question="Are you on a career break?",
        answer_value="No",
        answer_type=AnswerType.SINGLE_SELECT,
        choices=["Yes", "No"],
    )
    candidate = JobCandidate(
        stable_key="job:chip-chatbot",
        url="https://www.naukri.com/job-listings-software-engineer-acme-999",
        title="Software Engineer",
    )

    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        assert browser._chatbot_option_labels() == ["Yes", "No"]
        assert browser._chatbot_option_requires_save() is False
        result = browser._complete_chatbot_questionnaire(memory, candidate)

    assert result is not None
    assert result.submitted is True
    assert "closed itself" in result.message


def test_chatbot_text_input_takes_priority_over_skip_chip(tmp_path: Path) -> None:
    html = """
    <div class="_chatBotContainer" id="_mixedChatbotContainer">
      <div class="chatbot_Drawer chatbot_right">
        <div class="chatbot_MessageContainer">
          <ul class="list">
            <li class="botItem chatbot_ListItem">
              <div class="botMsg msg">
                <div><span>What is your current CTC in Lacs per annum?</span></div>
              </div>
            </li>
          </ul>
          <div class="footerInputBoxWrapper">
            <div class="textArea" contenteditable="true" data-placeholder="For example: 7 lakhs"></div>
          </div>
          <div class="chipsContainer">
            <div class="chatbot_Chips chatbot_ChipsInRow">
              <div class="chatbot_Chip chipInRow chipItem"><span>Skip this question</span></div>
            </div>
          </div>
        </div>
        <div class="sendMsgbtn_container">
          <div class="send">
            <div class="sendMsg" tabindex="0" onclick="document.getElementById('_mixedChatbotContainer').remove()">Save</div>
          </div>
        </div>
      </div>
    </div>
    """
    memory = AnswerMemory()
    memory.remember(
        question="What is your current CTC in Lacs per annum?",
        answer_value="10.5 Lpa",
        answer_type=AnswerType.TEXT,
    )
    candidate = JobCandidate(
        stable_key="job:mixed-chatbot",
        url="https://www.naukri.com/job-listings-software-engineer-acme-1000",
        title="Software Engineer",
    )

    with NaukriBrowser(tmp_path / "browser-profile", headless=True) as browser:
        browser.active_page.set_content(html)
        result = browser._complete_chatbot_questionnaire(memory, candidate)

    assert result is not None
    assert result.submitted is True
    assert "closed itself" in result.message
