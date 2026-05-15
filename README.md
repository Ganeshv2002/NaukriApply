# Naukri Apply Assistant

A local command-line assistant that reviews Naukri job listings against your resume and helps with direct applications after your approval.

The app stores your private profile, saved answers, browser login session, history, logs, and reports inside `data/`. That folder is ignored by Git and should not be uploaded to GitHub.

## What This App Does

- Reads your resume from PDF, DOCX, or TXT.
- Opens Naukri in a real browser using Playwright.
- Searches job results using your keywords, locations, or saved Naukri search URLs.
- Scores jobs against your resume.
- Reviews jobs and attempts direct applications from the local browser workflow.
- Saves answers to repeated application questions.
- Reuses saved answers only when the question, field type, and visible options match.
- Exports external company apply links to `data/reports/external-review-needed.xlsx`.
- Writes run reports to `data/reports/` and logs to `data/logs/naukri-assistant.log`.

## Before You Start

Install these first:

- Python 3.11 or newer: https://www.python.org/downloads/
- Git: https://git-scm.com/downloads

When installing Python on Windows, enable **Add python.exe to PATH**.

## One-Run Setup

Open PowerShell in this project folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

That script will:

- create a local virtual environment named `.venv`
- install this app and its Python packages
- install the Playwright Chromium browser

After setup, activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

You should then see `(.venv)` at the start of your PowerShell line.

## First-Time Use

Run these commands in order:

```powershell
naukri-assistant init
naukri-assistant login
naukri-assistant run
```

### 1. Create Your Local Profile

```powershell
naukri-assistant init
```

This asks for:

- your resume path
- target keywords
- preferred locations
- optional Naukri search URLs
- how many result pages to scan
- maximum jobs per run

Example resume path:

```text
C:\Users\YourName\Downloads\resume.pdf
```

If your path has spaces, pasting it with quotes is fine:

```text
"C:\Users\YourName\Downloads\my resume.pdf"
```

### 2. Login To Naukri

```powershell
naukri-assistant login
```

A browser will open. Login to Naukri manually. After login finishes, return to PowerShell and press Enter.

The browser session is saved locally under `data/browser-profile/`.

### 3. Run The Assistant

```powershell
naukri-assistant run
```

The assistant opens Naukri, reviews jobs, and processes the run from your local browser session.

The code has an action helper that supports these review actions:

```text
a = approve
s = skip
d = defer
o = open job
q = quit
```

At the moment, that helper defaults to approve in code. Review `naukri_assistant/workflow.py` before using the tool on a real account if you want manual approval prompts.

For application questions, it will reuse a saved answer when it is safe to do so. If the same question appears as a different field type, or the saved answer is not one of the visible options, it asks again and stores the new answer for future use.

## Useful Commands

List saved answers:

```powershell
naukri-assistant answers list
```

Add a saved answer manually:

```powershell
naukri-assistant answers add --question "Are you willing to relocate?" --answer "Yes" --type single-select
```

List job history:

```powershell
naukri-assistant history list
```

Run tests:

```powershell
python -m pytest
```

## If The Command Is Not Found

If `naukri-assistant` is not recognized, either activate the virtual environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or run the app through Python:

```powershell
python -m naukri_assistant init
python -m naukri_assistant login
python -m naukri_assistant run
```

## Manual Setup Without The Script

Use this only if `scripts/setup.ps1` fails:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

## Private Files

Do not commit or upload these files:

- `data/profile.json`
- `data/answers.json`
- `data/history.json`
- `data/browser-profile/`
- `data/logs/`
- `data/reports/`
- `.venv/`

They are ignored by `.gitignore`.

Before pushing to GitHub, check:

```powershell
git status --short
git ls-files | Select-String -Pattern "^data/"
```

The second command should print nothing.

## Reports

External-company jobs are exported to:

```text
data/reports/external-review-needed.xlsx
```

Each run also creates a JSON report under:

```text
data/reports/
```

## Notes

This app does not bypass CAPTCHA, login checks, warnings, rate limits, or platform restrictions. It uses a normal browser session.
