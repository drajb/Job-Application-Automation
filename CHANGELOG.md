# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows [SemVer](https://semver.org/).

## [0.2.0] — 2026-10-13

A safety and reliability overhaul plus job discovery. Upgrading: run `make migrate` (adds the `discovered_jobs` table).

### Added
- **Job discovery**: `watchlist.yaml` + `/scan` / `--scan` read public Greenhouse, Lever, Ashby and SmartRecruiters job boards, filter by title/location/age, rank by fit, and post new roles to Telegram with 🚀 Apply / 🙈 Skip. Optional daily scan (`SCAN_HOUR`).
- **Fit + keyword-gap report**: `--fit URL_OR_FILE`; fit and missing keywords also on every approval card.
- **`--doctor`** setup checker, `--done`, `--export`, `make setup`, `make check`, `make edit-profile`, `make backup`.
- Telegram `/help`, `/scan`, `/abort`; Skip / Take over / Abort buttons on questions.
- Configurable `APPLY_TIMEZONE`, submission window, `DAILY_CAP` (≤ 25), `COOLDOWN_DAYS` (≥ 30), `GEMINI_RPM` / `GEMINI_RPD`, `APPLY_HEADLESS`, `APPLY_AGENT_DB`, `APPLY_BROWSER_PROFILE`, `WATCHLIST_PATH`.
- Keyword fallback for email classification when Gemini is unavailable.
- Application status follows responses (response → interview → offer / rejected_by_company).
- CI: mypy, migration-vs-model check, Docker build on every PR, real dependency audit.

### Changed
- **You now approve a screenshot of the filled form**, not just the resume. Adapters `fill()` and never submit; the pipeline calls `submit()` after approval and checks for a confirmation page.
- Window and daily cap are re-checked right before Submit; applications run one at a time.
- Live runs (`--no-dry-run`) refuse to start without Telegram.
- **Validator** checks single tokens (not phrases), numbers with magnitude, lower-case tool names, URLs/emails, and truncation. Job-title words are no longer allowlisted.
- Tier-2 loop: submit clicks, foreign uploads and off-site navigation blocked in code; errors fed back to the model; confidence fails closed; passwords and salary never sent to the LLM.
- Learned answers: sensitive questions only reused on an exact match; company-specific answers not copied across companies; mid-similarity answers adapted and validated.
- Work-authorization questions answered Yes/No with the polarity each wording asks for.
- Telegram cards use HTML (MarkdownV2 cards were rejected by Telegram).
- Answers are routed to the question you replied to; `/done` and Take over act on the waiting run, and the browser stays open for handoffs.
- Renderer: isolated LibreOffice profile, timeout, output verified, UUID stamped with pypdf, neutral `<First>_<Last>_Resume.pdf` filename, real markdown formatting.
- Gemini via the `google-genai` SDK, with retries and truncation detection. Daily quota persisted and reset at midnight Pacific.
- Email: processed only once; failed messages retried; phishing checks on sender domain, DKIM and link host; OTP extraction ignores years/ZIP codes; stricter response matching.
- Vault CSV written atomically with 0600 permissions and formula escaping; passwords stored before sign-up starts.
- `.env` is loaded before paths are resolved (so `RESUME_SOURCE_DIR` in `.env` works); relative paths resolve from the repo root.
- Example resume is never selected as yours.

### Fixed
- Docker image build (v0.1.0 container was never published); `.dockerignore` keeps secrets out of images.
- Wheel now contains every module and the migrations.
- Ashby and SmartRecruiters selectors that failed on every run.
- Re-applying to the same URL crashed on a unique constraint.
- `--no-telegram` no longer stops the inbox monitor and scheduler.
- selectolax 1.0 removed the parser backend in use.
- Migration 0002 aligns nine columns with the models.

### Removed
- Unused FastAPI/uvicorn/tenacity dependencies; dead `execution/router.py`, `tier1_playwright.py`, `telegram_bot/handlers.py`.

## [0.1.0] — 2026-08-24

First public release.

### Added
- Tier-1 adapters: Greenhouse, Lever, Ashby, Workable, SmartRecruiters.
- Tier-2 Gemini JSON action loop; Tier-3 manual takeover.
- Resume validator with entity-based fabrication detection.
- `qa_log` semantic answer store (bge-small + sqlite-vec).
- IMAP listener, signup correlator, response classifier with Telegram alerts, daily digest.
- Encrypted vault with CSV mirror; setup wizard; Docker; CI.

### Safety
- `dry_run=True` default, 25/day cap, 90-day cooldown, submission window, Telegram chat allowlist.
