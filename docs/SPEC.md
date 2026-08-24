# SPEC.md — apply-agent

> Locked architectural decisions. PRs that violate §11 will be rejected.

This is a hand-selected job-application agent, not a bulk applier. **Volume target: 15-20 carefully chosen applications/day. Hard cap: 25.**

---

## 0. Mission

Selecting a job posting URL triggers an autonomous agent that:

1. Fetches and parses the JD.
2. Picks the best-matching base resume from `resumes/*` (under `RESUME_SOURCE_DIR`).
3. Tailors it to the JD (keyword alignment, bullet rephrasing — **never fabrication**).
4. If the portal requires an account → creates one, handles email confirmation, stores credentials in an encrypted vault, mirrors to CSV.
5. Opens the application URL via the right execution tier (deterministic Playwright → vision-driven Gemini → human takeover).
6. Fills the form using the encrypted profile + a learned Q&A store.
7. Pauses on uncertainty, asks the human via Telegram.
8. Pauses for human approval before final submit. Screenshot + tailoring diff posted to Telegram.
9. Logs the application with a UUID-stamped resume.
10. Monitors the inbox for responses. **Positive responses (interview / recruiter / offer) trigger high-priority Telegram alerts with email excerpt + matched application.**

The system gets smarter every time the human intervenes.

---

## 1. Architecture (LOCKED)

```
┌─────────────────────────────────────────────────────────────────┐
│                       USER (Telegram, mobile)                    │
└──────────┬──────────────────────────────────────────▲───────────┘
           │ /apply <url>, /handoff, /done, etc.      │ approvals,
           ▼                                          │ inbox alerts
┌─────────────────────────────────────────────────────────────┐
│  apply-agent (single Python process, src/main.py)            │
│   ├─ Telegram bot (python-telegram-bot, long polling)        │
│   ├─ IMAP listener (imap_tools IDLE)                         │
│   ├─ FastAPI internal endpoints (127.0.0.1:8080)             │
│   ├─ Orchestrator pipeline (apply_to)                        │
│   ├─ Resume tailor (Gemini 2.5 Flash)                        │
│   ├─ Execution router (Tier 1/2/3)                           │
│   ├─ Credential vault (age + CSV export)                     │
│   └─ SQLite + sqlite-vec (apply_agent.db)                    │
│                                                                │
│  Local Chromium (Playwright, dedicated profile)               │
│  LibreOffice headless (for docx → pdf)                        │
│  age (for at-rest encryption)                                 │
│  Local bge-small-en-v1.5 (embeddings)                         │
└─────────────────────────────────────────────────────────────┘
```

**Out of scope / not in this architecture**: pyautogui, computer-vision OCR, third-party captcha solvers, paid LLM APIs.

---

## 2. Constraints & Principles

- **Selected, not bulk.** 15-20/day target. Hard cap 25/day.
- **Human-in-the-loop is a feature.** Every submit goes through Telegram approval. Every unknown question pauses.
- **Truth over keywords.** Tailoring rewords existing facts. Never invents employers, dates, skills, tools.
- **Free runtime.** Gemini 2.5 Flash free tier (1,500 RPD / 15 RPM / 1M TPM). Worst-case load ~400 RPD.
- **Single-host.** Everything in one process on one box.
- **Per-portal accounts.** Email confirmation handled end-to-end by the agent. Credentials encrypted at rest, mirrored to CSV.
- **Browser hygiene.** Dedicated profile, no work-account cookies.
- **90-day cooldown** on `(company, role_title)` hash.

---

## 3. Execution Tiers (LOCKED)

### Tier 1 — Deterministic Playwright (no LLM driving)

Used for: Greenhouse, Lever, Ashby, Workable, SmartRecruiters. Per-ATS module under `src/ats/` with explicit selectors. LLM only for free-text essays at submit time. Speed: 30-90s per app. Cost: effectively $0.

### Tier 2 — vision-driven Gemini 2.5 Flash loop

Used for: anything not matched by Tier 1 (Workday, iCIMS, Taleo, custom portals). Per-app: 30-50 LLM calls. Well within free-tier RPD/RPM. Pause: confidence < 0.7 → Telegram handoff card.

### Tier 3 — Human takeover (escape hatch)

Used when: captcha not bypassable, complex multi-step Workday, LinkedIn Easy Apply with full bot detection. The agent does all prep, then pauses. Telegram alerts you; you grab the mouse and finish the form. Send `/done <app_id>` when done.

### Pre-flight Filters (before any tier runs)

1. **Cooldown**: `(company, role_title)` hash applied within 90 days → skip.
2. **H1B sponsor**: company has zero recent sponsorships → skip with Telegram note.
3. **Stale posting**: JD posted >30 days ago → flag, require explicit confirm.
4. **Salary floor**: JD range tops out below `desired_base_min` → skip with note.
5. **Daily cap**: today's count ≥ 25 → defer.
6. **Submission window**: outside configured window → defer.
7. **Rate-limit headroom**: Gemini RPD >80% consumed → defer.

---

## 4. Resume Tailor — Sacred Validator

1. Load resumes via `python-docx` / Markdown, embed at startup with `bge-small-en-v1.5`.
2. On new JD, embed JD → cosine-rank within family → pick top base resume.
3. Gemini 2.5 Flash rewrites bullets to align with JD vocabulary.
4. **Validator (CRITICAL)**: every employer / year / tool / framework / certification in the output must trace to source. Otherwise → REJECT, regenerate. Hard fail after 2 retries → escalate via Telegram.
5. Render via LibreOffice headless: `libreoffice --headless --convert-to pdf <docx>`.
6. Stamp UUID into PDF metadata for per-variant response-rate tracking.

---

## 5. Account Manager + Credential Vault

```python
async def ensure_account(portal: str, application_id: int) -> Credentials:
    if existing := vault.get(portal):
        return existing
    creds = Credentials(
        username=PROFILE.identity.email,
        password=generate_password(24),
    )
    expectation = create_email_expectation(
        application_id=application_id,
        sender_domain=derive_sender_domain(portal),
        purpose="verify_email",
        ttl_seconds=600,
    )
    await execution_router.run_signup(portal, creds)
    link = await wait_for_expectation(expectation.id, timeout=600)
    await execution_router.confirm_email(link)
    vault.store(portal, creds, verified=True)   # also regenerates CSV
    return creds
```

- Vault: SQLite + `age` encryption per row. Master key in `secrets/master.age.key` (gitignored).
- Loaded once at process start, kept in memory only.
- Passwords: 24 chars, mixed alphanumeric + symbols, unique per portal.
- Every vault write triggers CSV regeneration.

---

## 6. Email Monitor

Matching priority for responses:
1. Message-ID threading.
2. Sender domain ↔ `application.company`.
3. Fuzzy company match in subject/body.
4. Orphan recruiter outreach → still logged.

**Notification policy:**
- `interview_invite`, `recruiter_outreach`, `offer` → **immediate high-priority Telegram card** with email excerpt + matched application context.
- `confirmation` → silent log.
- `rejection` → silent log, daily digest only.
- `other` → daily digest.

---

## 7. HITL Training Loop

Agent PAUSES when:
- qa_log similarity < 0.7
- LLM confidence < 0.7
- Field category is `visa | salary | legal | felony | clearance`
- ATS shows captcha / "verify you're human"

Reply → answer fills, agent continues. Stored in `qa_log` with `source=human, confidence=1.0`.

**Batch analysis** (every 10 apps): clusters recent interventions, proposes new `profile.yaml` fields, proposes new `qa_log` seed entries, outputs markdown diff to `docs/training_proposals_<date>.md`.

---

## 8. Risk & Safety Rules

| Risk | Mitigation |
|---|---|
| Hallucinated resume content | Validator rejects any unseen entity. 2-retry hard fail. |
| Bot detection on hardened ATSes | Tier 3 human takeover. |
| Telegram bot hijack | chat_id allowlist + token in `.env` only. |
| Gemini quota exhaustion | Rate tracker pauses new apps at 95% RPD. Email classification continues. |
| Profile data leak | `profile.yaml` age-encrypted, gitignored. |
| Wrong company submission | Pre-submit screenshot + Telegram approval mandatory. |
| Duplicate apply | 90-day cooldown on (company, role_title). |
| Credential leak | age-encrypted vault, in-memory only after process start. |
| Phishing on verification | Verify sender domain matches expectation. |
| Captcha | Always escalate to Tier 3 takeover. No third-party solvers. |
| SMS / phone 2FA | Pause and ask human via Telegram (paste OTP). |

---

## 9. Locked Decisions (§11)

- **LLM**: Gemini 2.5 Flash via Google AI Studio free tier. No Anthropic, no OpenAI, no paid APIs.
- **Embeddings**: local `bge-small-en-v1.5`.
- **Encryption**: `age`.
- **Browser**: Chromium via Playwright, persistent profile `chrome-profile-apply/`.
- **Resume rendering**: `libreoffice --headless --convert-to pdf`.
- **Volume**: 15-20/day target. Hard cap 25/day. Hard cap 10 LinkedIn/day (Tier 3 only).
- **Quota cap**: 95% of Gemini daily RPD pauses new applications.
- **Submission window**: configurable, defaults to 10am–6pm in `America/Chicago`.
- **Cooldown**: 90 days on (company, role_title).
- **Password export**: plain CSV at `secrets/portal_passwords.csv`.
- **dry_run=True is the default**; `--no-dry-run` is opt-in per run.
- **LinkedIn Easy Apply**: Tier-3 only. Never automated.

---

## 10. Hard Rules

- DO NOT enable real submissions by default. `dry_run=True` always.
- DO NOT touch LinkedIn outside Tier 3 manual takeover.
- DO NOT commit `secrets/`, `*.db`, `chrome-profile-apply/`, `*.age.key`, or `profile.yaml`.
- DO NOT modify source resumes — they're truth source.
- DO NOT invent resume content. Validator failures are a feature.
- DO NOT submit outside the configured window.
- DO NOT bulk-apply. Past 25/day → refuse.
- DO NOT weaken the resume validator. Regenerate or escalate.
- DO NOT introduce Anthropic, OpenAI, or any paid API. Gemini free tier only.
