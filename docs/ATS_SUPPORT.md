# ATS support matrix

## Tier-1 (deterministic Playwright)

These are first-class. URL pattern → adapter → fill. ~30–90s per app. ~$0 cost.

| ATS | Status | Module | URL pattern | Notes |
|---|---|---|---|---|
| Greenhouse | ✅ stable | [`greenhouse.py`](../src/ats/greenhouse.py) | `boards.greenhouse.io`, `job-boards.greenhouse.io` | Most reliable. Tested against 50+ boards. |
| Lever | ✅ stable | [`lever.py`](../src/ats/lever.py) | `jobs.lever.co` | `/apply` page is separate. Custom Q&A walker handles most questions. |
| Ashby | ✅ stable | [`ashby.py`](../src/ats/ashby.py) | `jobs.ashbyhq.com` | React. Selectors use `[class*='Field_']` because Ashby ships hashed class names. |
| Workable | ✅ stable | [`workable.py`](../src/ats/workable.py) | `apply.workable.com` | Standard form. |
| SmartRecruiters | ✅ stable | [`smartrecruiters.py`](../src/ats/smartrecruiters.py) | `jobs.smartrecruiters.com` | Marks `requires_account=True` (most postings need a sign-in). |

## Tier-2 (vision-driven Gemini loop)

For ATSes without a Tier-1 adapter. The agent takes a stripped text snapshot of the page and asks Gemini "what's the next action?" in a constrained JSON grammar (`goto/click/fill/upload/scroll/wait/done`). Confidence < 0.7 triggers human handoff.

| ATS | Coverage | Caveats |
|---|---|---|
| Workday | Best-effort | Multi-page flows. May escalate to Tier-3 on the review step. |
| iCIMS | Best-effort | Lots of session-state quirks. |
| Taleo | Best-effort | Legacy ATS, varies by tenant. |
| Custom portals | Best-effort | Anything with a coherent form structure. |

If Tier-2 keeps escalating for an ATS you use a lot, consider writing a Tier-1 adapter for it — see [CONTRIBUTING.md](../CONTRIBUTING.md#adding-a-new-ats-adapter).

## Tier-3 (manual takeover — never automated)

| ATS | Why |
|---|---|
| LinkedIn Easy Apply | Bot detection is too aggressive. Auto-submit will burn the account. |
| Anything with a captcha | We do not use third-party captcha solvers. |

## Adding a new Tier-1 adapter

The contract is in [src/ats/base.py](../src/ats/base.py). 80% of an adapter is selectors; the rest is the form-walking helper. Start by copy-pasting `greenhouse.py` and changing:

1. The URL pattern in `can_handle()`.
2. The role / company / description selectors in `parse_job()`.
3. The form-field selectors in `fill()`.

Run against a real posting in headed mode (`--no-telegram` lets you skip the bot setup):

```bash
python -m src.main --apply https://jobs.example.com/posting/123
```

Watch the headed Chromium do its thing. When it gets stuck on a field, the selector is the bug. Defensive selectors (`.a, .b, .c`) are encouraged — ATSes love to rename classes.

## Selector decay

Selectors rot. When an adapter starts misbehaving:

1. Open a real posting on that ATS in your own browser.
2. Right-click the field → Inspect.
3. Update the selector list in the adapter.
4. Add a regression test if you can find a stable URL fixture.

PRs that fix selector decay are very welcome and reviewed fast.
