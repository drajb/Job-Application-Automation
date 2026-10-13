# Automated Job Applications

**Find good-fit jobs, tailor your resume to each one without inventing anything, fill the application, and submit only after you approve a screenshot from your phone.** Runs on your own machine on Gemini's free tier, so it costs $0/month.

[![CI](https://github.com/drajb/Job-Application-Automation/actions/workflows/ci.yml/badge.svg)](https://github.com/drajb/Job-Application-Automation/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/drajb/Job-Application-Automation?sort=semver)](https://github.com/drajb/Job-Application-Automation/releases)
[![Container](https://img.shields.io/badge/ghcr.io-container-2496ED?logo=docker&logoColor=white)](https://github.com/drajb/Job-Application-Automation/pkgs/container/job-application-automation)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Runtime cost: $0/mo](https://img.shields.io/badge/runtime%20cost-%240%2Fmo-brightgreen)](docs/SPEC.md)

```
/scan                      → 🔎 Acme — Senior Backend Engineer · Remote · Fit 78%
                              Missing: terraform, kafka            [🚀 Apply] [🙈 Skip]
🚀 Apply                   → tailors your resume · validates every fact · fills the form
                           → 🤔 "Are you willing to relocate?"  (you reply once; it remembers)
                           → 📸 screenshot of the filled form
                              🎯 Acme — Senior Backend Engineer · greenhouse · Fit 78%
                              Validator: ✅ every fact traced to your resume
                              • ~~Built REST APIs in Python~~ → Built Python REST APIs serving 3 teams
                                                            [✅ Submit] [✗ Reject] [🖥 Take over]
✅ Submit                  → re-checks the time window and daily cap → submits → confirms
...                        → 📬 INTERVIEW — Acme (Senior Backend Engineer), applied 6d ago
```

## Why this one

| | Bulk "auto-apply" bots | This project |
|---|---|---|
| Volume | Hundreds a day | You pick each one; daily cap ≤ 25 |
| Resume | Keyword-stuffed or invented | Reworded from **your** facts; a validator rejects anything new |
| Submitting | Automatic | Only after you approve a screenshot of the filled form |
| Your data | Their servers | Your machine; profile and passwords encrypted with `age` |
| Cost | Subscription | $0 (Gemini free tier + local models) |
| LinkedIn | Automated (risks your account) | Never automated |

## Features

- **Job discovery.** List companies in `watchlist.yaml`; `/scan` reads their public Greenhouse / Lever / Ashby / SmartRecruiters boards, filters by title, location and age, and ranks new roles by fit to your resume. No LLM calls.
- **Fit + keyword-gap report.** `--fit <url>` shows which skills a posting asks for that your resume does and doesn't mention.
- **Truthful tailoring.** Gemini rewrites your resume for the posting. The validator rejects any new employer, title word, year, number, tool, URL or email, and any truncated output. You see bullet-level diffs before approving.
- **Form filling.** Dedicated adapters for Greenhouse, Lever, Ashby, Workable and SmartRecruiters. An LLM action loop handles Workday, iCIMS and other sites, with submit clicks, file uploads and off-site navigation blocked in code.
- **Learns your answers.** Unknown questions come to Telegram; your reply is remembered. Work-authorization questions get the right yes/no for each wording. Sensitive questions are never answered from a fuzzy match.
- **You approve every submission**, on a screenshot of the filled form. Dry run is the default.
- **Inbox monitoring.** Instant alerts for interview invites, recruiter outreach and offers, matched to the application and resume variant. Daily 7pm digest.
- **Portal accounts.** Creates accounts when a site requires one, verifies the email, and keeps passwords in an encrypted vault (the LLM never sees them).
- **Guardrails.** Submission window, daily cap, 90-day cooldown, optional H1B-sponsor filter, salary floor, Gemini quota budgeting.
- **`--doctor`** checks your setup and tells you how to fix what's missing.

## Quickstart

On Linux, macOS or WSL2:

```bash
git clone https://github.com/drajb/Job-Application-Automation.git apply-agent
cd apply-agent
make setup                          # venv, deps, Chromium, .env + profile templates, doctor
mkdir -p resumes/master && $EDITOR resumes/master/Resume_v1.md
make keygen && $EDITOR secrets/profile.yaml && make encrypt-profile
echo "GEMINI_API_KEY=..." >> .env   # free: https://aistudio.google.com/apikey
make migrate && make doctor
python -m src.main --fit   https://boards.greenhouse.io/<company>/jobs/<id>
python -m src.main --apply https://boards.greenhouse.io/<company>/jobs/<id>   # dry run
```

Then add Telegram (5 minutes) for approvals, questions and alerts, and `make run`. Full walkthrough: **[docs/QUICKSTART.md](docs/QUICKSTART.md)**.

Docker (headless):

```bash
docker compose up -d     # or image: ghcr.io/drajb/job-application-automation:latest
```

## Commands

| Telegram | CLI | |
|---|---|---|
| `/apply <url>` | `--apply URL` | Tailor, fill, screenshot, ask for approval |
| `/scan` | `--scan` | New matching roles from your watchlist |
| — | `--fit URL_OR_FILE` | Fit score + missing keywords |
| `/pending`, `/status` | `--export PATH` | What's waiting; stats; CSV export |
| `/done <id>`, `/abort <id>` | `--done ID` | Finish or stop an application |
| — | `--doctor` | Check setup |

Settings and every env var: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## How safe is it?

| Risk | Mitigation |
|---|---|
| Invented resume content | [Validator](src/resume/validator.py) + bullet diffs on the approval card |
| Submitting something you didn't see | Approval on a screenshot of the filled form; dry run by default; live runs need Telegram |
| A job page manipulating the AI | Untrusted-data prompts; the action loop can't submit, upload other files or leave the site |
| Phishing "verify your email" | Sender domain, DKIM and link host must all match the portal |
| Spamming recruiters | Daily cap, cooldown, submission window, one application at a time |
| Someone else using your bot | Every update checked against your chat ID |
| Credential leaks | `age`-encrypted vault; passwords never sent to the LLM |
| Captchas | Handed to you. No solvers. |

Details: [SECURITY.md](SECURITY.md) · [docs/PRIVACY.md](docs/PRIVACY.md).

## Docs

[QUICKSTART](docs/QUICKSTART.md) · [CONFIGURATION](docs/CONFIGURATION.md) · [RUNBOOK](docs/RUNBOOK.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [ATS support](docs/ATS_SUPPORT.md) · [SPEC](docs/SPEC.md) · [PRIVACY](docs/PRIVACY.md) · [FAQ](docs/FAQ.md) · [LinkedIn](docs/LINKEDIN.md) · [ROADMAP](ROADMAP.md) · [CHANGELOG](CHANGELOG.md)

## Contributing

New ATS adapters, selector fixes, validator test cases and discovery sources are the most useful. See [CONTRIBUTING.md](CONTRIBUTING.md). Report vulnerabilities privately via [SECURITY.md](SECURITY.md).

If this helped your search, a ⭐ helps other job seekers find it.

## License

[MIT](LICENSE). See [NOTICE.md](NOTICE.md) for the (non-binding) spirit it's shared in.

Built with [Gemini](https://ai.google.dev/), [Playwright](https://playwright.dev/), [python-telegram-bot](https://python-telegram-bot.org/), [imap-tools](https://github.com/ikvk/imap_tools), [bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5), [sqlite-vec](https://github.com/asg017/sqlite-vec), [age](https://github.com/FiloSottile/age) and [LibreOffice](https://www.libreoffice.org/).
