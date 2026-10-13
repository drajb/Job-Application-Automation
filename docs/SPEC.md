# SPEC — apply-agent

> The decisions in §9 and the rules in §10 are locked. PRs that break them are rejected.

A hand-selected job-application agent, not a bulk applier. **Target: a handful to ~20 well-matched applications a day. Hard cap: 25.**

---

## 0. Mission

Given a job posting URL (yours, or one found by discovery), the agent:

1. Fetches and parses the posting.
2. Picks the best base resume from `RESUME_SOURCE_DIR`.
3. Tailors it to the posting (wording, ordering, emphasis), **never adding facts**.
4. Fills the application form from your encrypted profile and learned answers.
5. Asks you on Telegram when it meets a question it can't answer confidently, and remembers your answer.
6. Shows you a screenshot of the filled form, the tailored-bullet diffs, a fit score and the missing keywords, and waits for your approval.
7. Submits only after approval, only in a live run, and confirms the ATS accepted it.
8. Creates portal accounts when needed (encrypted vault, email verification handled).
9. Watches your inbox and alerts you immediately on interview invites, recruiter outreach and offers.

It also finds roles: it scans the public job boards of companies you list and ranks openings by fit.

---

## 1. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     YOU (Telegram, phone)                     │
└──────────┬───────────────────────────────────────▲───────────┘
           │ /apply, /scan, replies, buttons        │ screenshots, approvals,
           ▼                                        │ questions, inbox alerts
┌──────────────────────────────────────────────────────────────┐
│ apply-agent (one Python process, src/main.py)                 │
│  ├─ Telegram bot (python-telegram-bot, long polling)          │
│  ├─ Pipeline apply_to() — one application at a time           │
│  ├─ Tiers: 1 adapters · 2 Gemini loop · 3 you                 │
│  ├─ Resume select · tailor (Gemini) · validator · renderer    │
│  ├─ Job discovery (public ATS feeds, local fit scoring)       │
│  ├─ IMAP listener + classifier + matcher + signup correlator  │
│  ├─ Scheduler (digest, daily scan)                            │
│  ├─ Vault (age per row + CSV mirror)                          │
│  └─ SQLite (+ sqlite-vec)                                     │
│ Playwright Chromium (dedicated profile) · LibreOffice ·       │
│ age · local bge-small-en-v1.5                                 │
└──────────────────────────────────────────────────────────────┘
```

No inbound ports. Everything is outbound HTTPS.

---

## 2. Principles

- **Selected, not bulk.** Daily cap (≤ 25), 90-day cooldown per (company, role), submission window.
- **Human in the loop.** Every submission is approved by you, on a screenshot of the filled form.
- **Truth over keywords.** Tailoring rewords your facts; it never adds employers, titles, dates, numbers or tools.
- **Free runtime.** Gemini free tier; everything else local.
- **One host, one process, one application at a time.**

---

## 3. Execution tiers

### Tier 1: dedicated adapters

Greenhouse, Lever, Ashby, Workable, SmartRecruiters. Fixed selectors. `fill()` never submits; `submit()` is a separate step the pipeline calls after approval.

### Tier 2: Gemini action loop

Everything else. One JSON action per step from a text snapshot of the page. Safety is in code: no submit clicks (the loop returns `ready`), uploads limited to your tailored resume, navigation limited to the starting site, missing confidence = 0 → handoff, no salary or passwords in prompts.

### Tier 3: you

LinkedIn (always), captchas, stuck forms, low confidence. The browser stays open; finish and send `/done <id>`.

### Pre-flight (before any LLM call)

1. Submission window (`APPLY_TIMEZONE`, default 10:00–18:00) → defer
2. Daily cap → defer
3. 90-day cooldown on normalised (company, role) → skip
4. H1B sponsor dataset, if your profile needs sponsorship → skip zero-sponsor companies
5. Salary floor → skip
6. Gemini quota ≥ 80% → defer

Window and cap are checked **again** right before the submit click.

---

## 4. Resume tailor and the validator

1. Select: route to a variant folder by role keywords, then cosine-rank its files with local embeddings. Files named `*example*` are never used.
2. Tailor with Gemini (job description marked as untrusted data).
3. **Validate.** Every year, capitalised token, number (with magnitude), tech-lexicon tool, URL and email in the draft must appear in the source resume or profile. Empty or truncated drafts (shorter than half the source, or missing most of its dates) are rejected. Two attempts with feedback, then stop and tell the human.
4. Render md → docx → PDF with LibreOffice (isolated profile, timeout, output verified), stamp the run UUID into the PDF metadata. A live run refuses to continue without a valid PDF.

---

## 5. Accounts and vault

When a Tier-2 portal requires an account (live runs only): generate a 24-character password, **store it in the vault first** (unverified), drive the sign-up form with the password as a placeholder the LLM never sees, wait for the verification email, open the link, mark verified.

Vault: per-row `age` encryption; master key in `secrets/master.age.key`. Every write regenerates `secrets/portal_passwords.csv` (0600, atomic, formula-escaped).

---

## 6. Email monitor

- **Sign-up verification:** sender is the expected registrable domain or a subdomain, DKIM passes when recorded, link host on that domain.
- **Matching responses:** sender domain = company name, else company name as a whole word in the subject (or body for distinctive names). Only submitted applications, newest first.
- **Notifications:** interview / recruiter / offer → immediate Telegram card. Confirmation → silent. Rejection / other → daily digest.
- Application status moves forward on responses (response → interview → offer, or rejected_by_company).
- Without Gemini, classification falls back to keyword rules. Failed messages stay unread and are retried up to 3 times.

---

## 7. Learning loop

For a question the profile can't answer:

- `qa_log` similarity ≥ 0.85 → reuse (company-specific answers only for the same company).
- 0.70–0.85 → Gemini adapts a long prior answer; the result must pass the validator.
- Otherwise → ask you on Telegram (the stuck timer pauses while you answer).
- **Sensitive questions** (sponsorship, authorization, salary, criminal history, clearance, legal) are only reused on an exact match; work-authorization yes/no comes straight from the profile with the polarity the question asks for.

Your answers are stored with `source=human` and logged as training runs. `scripts/analyze_training.py` writes proposals to `data/training_proposals_<date>.md`.

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| Fabricated resume content | Validator (§4) + bullet diffs on the approval card |
| Wrong submission | Approval on a screenshot of the filled form; confirmation-page check after submit |
| Submitting in a dry run | Submit is a separate step the pipeline only calls when `dry_run` is off |
| Submitting without approval | Live runs refuse to start without Telegram |
| Prompt injection from job pages | Untrusted-data framing + code-level action restrictions (§3) |
| Bot hijack | chat_id allowlist on every update |
| Quota exhaustion | Persisted daily counter (Pacific reset); new apps defer at 80%, hard stop at 95% |
| Phishing verification email | §6 checks |
| Duplicate applications | Cooldown + already-submitted URL check |
| Captcha | Tier 3. No solvers. |

---

## 9. Locked decisions

- **LLM:** Gemini 2.5 Flash (`google-genai`). No other provider.
- **Embeddings:** local `bge-small-en-v1.5`.
- **Encryption:** `age`.
- **Browser:** Playwright Chromium with a dedicated persistent profile.
- **Rendering:** LibreOffice headless.
- **Volume:** hard cap 25/day (configurable lower only).
- **Cooldown:** 90 days default, 30 days minimum.
- **Window:** configurable; default 10:00–18:00 America/Chicago.
- **`dry_run=True` default.** Live runs need Telegram approval for every submit.
- **LinkedIn:** never automated.

---

## 10. Hard rules

- Never submit by default; never submit without approval.
- Never automate LinkedIn applications.
- Never commit `secrets/`, `.env`, `*.db`, `*.age.key`, `profile.yaml`, `watchlist.yaml`, or the browser profile.
- Never modify source resumes.
- Never invent resume content or weaken the validator.
- Never submit outside the window or past the cap.
- Never add another LLM provider or a paid API.
