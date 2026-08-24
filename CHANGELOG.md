# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows [SemVer](https://semver.org/).

## [0.1.0] — 2026-08-24

First public release.

### Added
- Initial public release.
- Tier-1 adapters: Greenhouse, Lever, Ashby, Workable, SmartRecruiters.
- Tier-2 vision-driven loop on Gemini 2.5 Flash with constrained JSON action grammar.
- Tier-3 manual takeover with Telegram screenshot handoff.
- Sacred resume validator with entity-based fabrication detection.
- `qa_log` semantic-search store (bge-small + sqlite-vec) with reuse / rephrase / pause thresholds.
- IMAP IDLE listener with signup correlator (verify-email link + 4–8 digit OTP).
- Gemini-based response classifier into 6 categories with high-priority Telegram alerts.
- Per-variant response-rate dashboard and daily 7pm-local digest.
- LinkedIn referral scan + DM drafter (manual paste; never sends).
- LinkedIn Easy Apply support **only** via Tier-3 takeover — agent prepares, you finish.
- Setup wizard (`make wizard`).
- Docker + docker-compose for polling mode.
- GitHub Actions CI: lint, test, dependency audit, personal-marker scan.
- Pre-commit hooks (ruff, large-file guard, private-key detection, personal-marker rejection).
- 68 pytest tests (unit + end-to-end pipeline wiring).
- Comprehensive docs: SPEC, ARCHITECTURE, QUICKSTART, CONFIGURATION, RUNBOOK, ATS_SUPPORT, PRIVACY, FAQ.

### Safety
- `dry_run=True` is the global default. `--no-dry-run` is opt-in per run.
- 25/day hard cap, 90-day cooldown on (company, role).
- Configurable submission window (default 10am–6pm in `America/Chicago`).
- Per-row `age`-encrypted vault, CSV mirror is one-way (vault → CSV).
- Telegram `chat_id` allowlist on every command + callback.

### Locked decisions
- Gemini 2.5 Flash only. No other LLM provider.
- Local `bge-small-en-v1.5` for embeddings.
- `age` for at-rest encryption.
- Chromium via Playwright with a dedicated persistent profile.
