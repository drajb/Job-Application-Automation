# Roadmap

What's likely, what's possible, what's out of scope. PRs that match the "likely" column will be reviewed fast.

## Likely (next 3 months)

- **Migrate to the `google-genai` SDK.** We currently use `google-generativeai`, which Google has deprecated in favour of `google-genai`. The current SDK still works (and is pinned), but the client in `src/llm/client.py` should move to the new package. Contained change — only `src/llm/client.py` imports it.
- **Workday Tier-1 adapter.** Workday is the single most-requested addition. Currently handled by the Tier-2 loop, which works but uses more quota.
- **Job-board ingestion.** A `/scout` command that takes a search query, surfaces matching postings from Greenhouse / Lever / Ashby boards, and lets you `/apply` from the list.
- **Cover-letter generator** with the same validator contract as the resume tailor.
- **Configurable submission window timezone** via env var (currently `America/Chicago` hardcoded).
- **Cooldown override** with a force-flag (for legitimate re-applies after >90 days when role re-opens).
- **Web UI** as an optional alternative to Telegram. (Approval cards on a local dashboard.)
- **Streamlit or simple-FastAPI dashboard** for the response-rate stats.

## Possible (open to a strong PR)

- More email providers documented with copy-pasteable IMAP settings.
- Per-resume-variant per-company A/B tracking with statistical significance.
- A "shadow" mode where the agent emails the tailored resume + answer doc to you instead of submitting, useful for high-stakes applications.
- Discord and Slack adapters mirroring the Telegram surface.
- Per-portal answer profiles (different desired comp for different verticals).
- Offline JD ingestion: paste a JD into Telegram and apply later when the URL is fresh.

## Won't do (locked decisions)

- **OpenAI / Anthropic / paid LLM providers.** The whole point is $0/mo runtime. PRs adding these will be rejected.
- **Bulk apply.** The 25/day cap is non-negotiable.
- **LinkedIn Easy Apply automation.** Tier-3 manual only, forever.
- **Captcha bypass via paid solvers** (2Captcha, AntiCaptcha, etc.). Always escalate to Tier-3.
- **Cloud-hosted SaaS version.** This is a self-hosted tool. If you want to host it as a service for others, fork it.
- **Weakening the validator.** If it false-positives, add tests; we extend the allowlist with evidence.

## Wanted: prompt improvements

If you've tuned the tailor or essay prompt and it consistently produces better output, PR it. We'll A/B against a small benchmark before merging.
