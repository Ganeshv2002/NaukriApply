# Naukri Resume-Matched Application Assistant

This project is a local CLI assistant for reviewing Naukri job results against a resume and applying only after explicit user approval.

## What it does

- Stores local profile, answer memory, job history, and a dedicated browser session under `data/`.
- Parses PDF, DOCX, and TXT resumes.
- Scores visible Naukri job results against resume content and saved search preferences.
- Opens a headed browser using a persistent Playwright profile.
- Requires terminal approval before attempting any application action.
- Saves answers to recurring screening questions for future reuse.
- Handles direct-apply chatbot questionnaires by reusing saved answers or prompting in the terminal, then waits 2 seconds after each chatbot response.
- Flags external-company redirect jobs instead of treating them like uniform in-site applications.
- Exports external-company jobs to `data/reports/external-review-needed.xlsx`.
- Writes run summaries to `data/reports/` and logs to `data/logs/naukri-assistant.log`.

## Install

```powershell
python -m pip install -e .[dev]
python -m playwright install chromium
```

## Commands

```powershell
naukri-assistant init
naukri-assistant login
naukri-assistant run
naukri-assistant answers list
naukri-assistant history list
```

If the installed script directory is not on `PATH`, the same commands work through:

```powershell
python -m naukri_assistant init
python -m naukri_assistant login
python -m naukri_assistant run
```


## Search configuration

`init` asks for resume path, keywords, preferred locations, and optional explicit Naukri search URLs. If no URL is provided, the tool creates a default search URL using the stored keywords and target experience.

Explicit URLs are usually the most reliable option when Naukri changes its search URL shape.

The tool now defaults to a 7-day posting freshness rule:

- Search URLs are normalized with `jobAge=7`.
- Visible result cards are accepted only when their posted-age text can be parsed as 7 days old or newer.
- Cards with missing or unrecognized age text are skipped so older jobs do not enter the review queue accidentally.

## Browser behavior

- `login` opens Naukri in a headed browser and waits for you to finish manual sign-in.
- `run` reuses the dedicated local browser profile from `data/browser-profile/`.
- The automation intentionally stays user-driven and approval-gated.
- The run path does not attempt to bypass CAPTCHA, login checks, warnings, rate limits, or platform restrictions.

## Reports

External-company jobs are exported with these fields:

- Job name
- Company name
- Job ID
- Apply link
- Experience required
- Tech stack/skills
- Source
- Status

The workbook is deduplicated across reruns by Job ID when available, then by apply link, then by job/company fallback.
