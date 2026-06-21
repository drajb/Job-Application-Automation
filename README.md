# apply-agent

> A truthful, human-in-the-loop job-application agent. Pick a job posting, watch the agent tailor your resume, fill the form, and wait for your Telegram approval before it touches Submit.

[![CI](https://github.com/drajb/Job-Application-Automation/actions/workflows/ci.yml/badge.svg)](https://github.com/drajb/Job-Application-Automation/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Runtime cost: $0/mo](https://img.shields.io/badge/runtime%20cost-%240%2Fmo-brightgreen)](docs/SPEC.md)
[![Validator: sacred](https://img.shields.io/badge/validator-sacred-red)](src/resume/validator.py)

## What this is

A hand-selected applier, not a bulk applier. Target: **15–20 carefully chosen applications/day**, hard cap 25. For each application, the agent:

1. Detects the ATS (Greenhouse, Lever, Ashby, Workable, SmartRecruiters; falls back to a vision-driven Tier-2 loop for Workday / iCIMS / custom).
2. Picks the best resume variant from your `resumes/` folder and **tailors it to the JD** with Gemini Flash.
3. Validates the tailored output: **every employer, year, tool, and metric must trace to your source resume.** Hallucinations get rejected, regenerated, then escalated to you.
4. Renders to PDF with a UUID stamped into the metadata so you can A/B response rates per variant.
5. Persists the application, posts a **Telegram approval card** with bullet-level diffs, and waits for ✅ Submit.
6. On approval, fills the form (still doesn't click Submit unless you pass `--no-dry-run`).
7. Monitors the inbox for responses. **Interview / recruiter / offer emails trigger immediate high-priority Telegram alerts** with excerpt + matched application context.

It gets smarter every time you intervene. Every answer you supply through Telegram goes into a semantic `qa_log` and is reused (verbatim above 0.85 similarity, rephrased between 0.70 and 0.85, escalated below).

## What this is **not**

- Not a bulk applier. The pre-flight rejects past 25/day, refuses outside 10am–6pm in your local submit window, and enforces a 90-day cooldown on `(company, role)`.
- Not a Submit-by-default tool. `dry_run=True` is the **safety default**. You explicitly opt in with `--no-dry-run` once you've watched a dry run.
- Not a resume rewriter. The validator rejects any tailored output that introduces facts not in the source `.docx`/`.md` — no embellishment, no fabricated metrics.
- Not a LinkedIn Easy Apply bot. LinkedIn is **Tier-3 (manual takeover) only**. The agent prepares everything and hands you the wheel.

## Features

| Area | What you get |
|---|---|
| **ATS adapters** | Greenhouse, Lever, Ashby, Workable, SmartRecruiters (Tier-1 deterministic). Workday / iCIMS / custom (Tier-2 vision loop). LinkedIn (Tier-3 manual). |
| **Truthfulness** | Sacred validator with entity extraction (years, acronyms, proper nouns), 2-retry regenerate, then human escalation. |
| **HITL** | Telegram approval before every Submit. Inline buttons for ✅ Submit / ✗ Reject / 📷 Screenshot / ✏ Edit. Pause/resume on uncertainty. |
| **Learning** | `qa_log` semantic store. Local `bge-small-en-v1.5` + `sqlite-vec` for cosine ranking. Reuse > 0.85, rephrase 0.70-0.85, pause < 0.70. |
| **Email monitoring** | IMAP IDLE listener. Signup-verify correlator + 4–8-digit OTP extractor. Gemini classifier into 6 response categories. High-priority alerts on interview/recruiter/offer. |
| **Encryption** | Per-row `age` encryption of portal credentials. Master key never written to logs. CSV mirror at `secrets/portal_passwords.csv` for human read. |
| **Pre-flight** | Submission window, daily cap, 90-day cooldown, salary floor, H1B sponsor pre-filter, Gemini quota headroom. |
| **Observability** | Per-variant response-rate dashboard. Daily 7pm-local digest. Training-run analyzer that proposes new `qa_log` seeds every 10 apps. |
| **Backup** | Nightly tar.gz of `secrets/`, `data/`, and the DB. Keeps last 30. |
| **Cost** | **$0/mo** runtime. Gemini 2.5 Flash free tier (15 RPM / 1500 RPD / 1M TPM). |

## Quickstart (5 minutes)

```bash
# Inside WSL2 Ubuntu (or any Linux with Python 3.11+):
git clone https://github.com/drajb/Job-Application-Automation.git apply-agent
cd apply-agent
make dev-install
cp .env.example .env             # fill in keys as you get them
make keygen                      # creates secrets/master.age.key — BACK IT UP
cp profile.example.yaml secrets/profile.yaml
$EDITOR secrets/profile.yaml     # fill in your details
make encrypt-profile             # encrypts to .age, removes plaintext
make migrate
make test                        # 55+ tests should pass
make run                         # boots Telegram bot + IMAP + scheduler
```

From Telegram:
```
/apply https://boards.greenhouse.io/<some-company>/jobs/<id>
```
You'll get an approval card. The agent stops at dry-run by default; pass `--no-dry-run` only after you've verified the tailored output is good.

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for the unhurried walkthrough.

## How safe is it?

| Risk | Mitigation |
|---|---|
| Hallucinated resume content | [Sacred validator](src/resume/validator.py) rejects unseen entities. 2-retry hard fail, then Telegram escalation. |
| Bot detection on hardened ATSes | Tier-3 manual takeover. The agent does all prep, you finish in a real browser window. |
| Telegram bot hijack | chat_id allowlist enforced on every command + callback. |
| Wrong company submission | Pre-submit screenshot + Telegram approval card with bullet diffs. Mandatory. |
| Credential leak | `age`-encrypted vault. Master key in `secrets/master.age.key` (gitignored). Decrypted only in memory after process start. |
| Captcha | Always escalate to Tier-3 takeover. No third-party solvers. |
| Phishing in verification email | Sender domain match + intentional expectation lifecycle. |
| Wrong submission window | Hard refuse outside 10am–6pm in the configured timezone. |
| Quota exhaustion | Rate tracker pauses new applications at 95% of Gemini's daily RPD. |

## Architecture (one-pager)

```
┌─────────────────────────────────────────────────────────────────┐
│                       YOU (Telegram, mobile)                     │
└──────────┬──────────────────────────────────────────▲───────────┘
           │ /apply <url>, /handoff, /done, etc.      │ approvals,
           ▼                                          │ inbox alerts
┌─────────────────────────────────────────────────────────────┐
│  apply-agent (single Python process, src/main.py)            │
│   ├─ Telegram bot (python-telegram-bot, long polling)        │
│   ├─ IMAP IDLE listener (imap_tools, any IMAP server)        │
│   ├─ FastAPI internal endpoints (127.0.0.1:8080)             │
│   ├─ Orchestrator (apply_to)                                 │
│   │    ├─ Resume selector → tailor → validator → renderer    │
│   │    ├─ Pre-flight (window, cap, cooldown, salary, quota)  │
│   │    └─ Telegram approval gate                             │
│   ├─ Execution router (Tier 1 / Tier 2 / Tier 3)             │
│   ├─ Account vault (age + CSV mirror)                        │
│   ├─ Email handler (signup correlator + classifier)          │
│   └─ SQLite + sqlite-vec (apply_agent.db)                    │
│                                                                │
│  Local Chromium (Playwright, dedicated profile)               │
│  Local bge-small-en-v1.5 (embeddings)                         │
│  Local LibreOffice (docx → pdf)                               │
└─────────────────────────────────────────────────────────────┘
```

Full diagram + module-by-module breakdown in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Configuration

All knobs are env vars. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full list. Minimum to run:

| Var                       | Required for                       | Where to get it                          |
|---------------------------|------------------------------------|------------------------------------------|
| `GEMINI_API_KEY`          | Resume tailoring + classifier      | https://aistudio.google.com/apikey       |
| `TELEGRAM_BOT_TOKEN`      | HITL approval                      | @BotFather on Telegram                   |
| `TELEGRAM_CHAT_ID`        | HITL approval                      | `getUpdates` after messaging your bot    |
| `APPLY_EMAIL_USER`        | Email monitoring + signup verify   | A dedicated job-application email        |
| `APPLY_EMAIL_PASSWORD`    | Email monitoring + signup verify   | App password (enable 2FA first)          |
| `APPLY_EMAIL_IMAP_HOST`   | Email monitoring                   | Defaults to `imap.gmx.com`               |
| `RESUME_SOURCE_DIR`       | Resume selection                   | Defaults to `./resumes/`                 |

Missing keys cause clear startup warnings, not crashes. The affected subsystem disables itself and the rest of the agent runs.

## Make targets

| Target               | What it does                                              |
|----------------------|-----------------------------------------------------------|
| `make install`       | venv + runtime deps                                       |
| `make dev-install`   | + pytest/ruff/mypy                                        |
| `make run`           | `python -m src.main` (polling)                            |
| `make test`          | pytest                                                    |
| `make lint`          | ruff check                                                |
| `make migrate`       | apply alembic migrations                                  |
| `make keygen`        | generate `secrets/master.age.key` (run ONCE; back it up)  |
| `make encrypt-profile`| encrypt `secrets/profile.yaml` → `.age`, remove plaintext |
| `make passwords`     | print path to `secrets/portal_passwords.csv`              |
| `make clean`         | wipe caches; secrets and DB untouched                     |

## Where to read next

1. [docs/QUICKSTART.md](docs/QUICKSTART.md) — get from zero to your first dry-run application in 30 minutes.
2. [docs/SPEC.md](docs/SPEC.md) — the locked architectural decisions. Read before opening a substantive PR.
3. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — diagrams, module boundaries, data flow.
4. [docs/CONFIGURATION.md](docs/CONFIGURATION.md) — every env var and CLI flag.
5. [docs/ATS_SUPPORT.md](docs/ATS_SUPPORT.md) — supported ATSes + how to add a new one.
6. [docs/PRIVACY.md](docs/PRIVACY.md) — what data is stored, where, and how encryption works.
7. [docs/FAQ.md](docs/FAQ.md) — common questions.

## Contributing

PRs welcome — especially new ATS adapters, prompt improvements, and additional pre-flight checks. See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow + how to add a new ATS adapter.

Found a vulnerability? See [SECURITY.md](SECURITY.md) for responsible disclosure.

## License

[MIT](LICENSE). Use it, fork it, ship it. Attribution appreciated but not required.

## Acknowledgements

Built with [Gemini 2.5 Flash](https://ai.google.dev/), [Playwright](https://playwright.dev/), [python-telegram-bot](https://python-telegram-bot.org/), [imap-tools](https://github.com/ikvk/imap_tools), [bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5), [sqlite-vec](https://github.com/asg017/sqlite-vec), [age](https://github.com/FiloSottile/age), and [LibreOffice headless](https://www.libreoffice.org/).
