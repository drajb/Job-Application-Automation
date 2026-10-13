# ATS support

## Tier 1: dedicated adapters

Fixed selectors, no LLM driving. Questions on the form go through the shared classifier ([src/ats/fields.py](../src/ats/fields.py)): profile answers first (with correct yes/no polarity for work-authorization questions), then your learned answers, then a Telegram question to you.

| ATS | Adapter | Hosts | Notes |
|---|---|---|---|
| Greenhouse | [`greenhouse.py`](../src/ats/greenhouse.py) | `boards.greenhouse.io`, `job-boards.greenhouse.io` | Classic and new board layouts. |
| Lever | [`lever.py`](../src/ats/lever.py) | `jobs.lever.co` | Follows the separate `/apply` page. |
| Ashby | [`ashby.py`](../src/ats/ashby.py) | `jobs.ashbyhq.com` | Hashed class names → attribute-substring selectors. |
| Workable | [`workable.py`](../src/ats/workable.py) | `apply.workable.com` | |
| SmartRecruiters | [`smartrecruiters.py`](../src/ats/smartrecruiters.py) | `jobs.smartrecruiters.com` | Guest "I'm interested" flow. |

Selectors drift as ATSes change their pages. If an adapter misbehaves, see "Selector decay" below.

## Tier 2: LLM-driven loop

For everything else (Workday, iCIMS, Taleo, company career sites). Each step the agent sends Gemini a text snapshot of the page and its form controls and gets back one JSON action: `click`, `fill`, `select`, `upload`, `goto`, `scroll`, `wait`, `need_account` or `ready`.

Enforced in code, not just in the prompt:

- The loop never clicks a submit-like button; it returns `ready` and the pipeline submits only after your approval.
- `upload` only ever uploads your tailored resume.
- `goto` can't leave the site the application started on.
- Missing or unparseable confidence counts as 0, which hands off to you.
- Salary and passwords are never in the prompt.

If a portal needs an account, a live run creates one (password stored in the encrypted vault, email verified via your inbox). A dry run stops and tells you.

Tier 2 uses one Gemini request per step, so a long Workday form can use 30+ requests.

## Tier 3: you

| Case | Why |
|---|---|
| LinkedIn (any URL, including `lnkd.in`) | Bot detection; automation risks your real account. Never automated. |
| Captchas, anything stuck or uncertain | No captcha solvers. The browser stays open, you finish, then `/done <id>`. |

## Adding a Tier-1 adapter

1. Read [src/ats/base.py](../src/ats/base.py) (the `parse_job` / `fill` / `submit` contract) and [src/ats/greenhouse.py](../src/ats/greenhouse.py).
2. Create `src/ats/<name>.py`. Use the helpers in [src/ats/common.py](../src/ats/common.py): `fill_if`, `upload_resume`, `answer_groups`. Set `submit_selectors`. **`fill()` must never click Submit.**
3. Register the hostname in `_ats_for()`, add the name to `_TIER1`, and return your class from `adapter_for()` in [src/ats/detector.py](../src/ats/detector.py).
4. Add detection tests (see `tests/test_ats_adapters.py`).
5. Try it on a real posting in dry-run: `python -m src.main --apply <url>`, and check the screenshot in `data/screenshots/`.

## Selector decay

1. Open a posting on that ATS in your own browser, right-click the field → Inspect.
2. Update the adapter's selector list (comma-separated alternates are fine).
3. Dry-run again.

Selector-fix PRs are reviewed quickly.
