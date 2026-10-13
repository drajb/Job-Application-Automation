# Roadmap

PRs matching "Next" get reviewed first.

## Done in 0.2

- Approval of the **filled form** (screenshot) instead of just the resume; submit only after approval, with a confirmation-page check.
- Job discovery from public Greenhouse / Lever / Ashby / SmartRecruiters boards, fit scoring and keyword-gap reports.
- `--doctor`, `--fit`, `--scan`, `--export`, `make setup`.
- Configurable timezone, submission window, daily cap, Gemini limits.
- Migrated to the `google-genai` SDK.

## Next

- **Workday Tier-1 adapter.** The most-requested one; Tier 2 handles it today but uses more quota.
- **Cover letters and essay answers** with the same validator contract as the resume tailor.
- **More discovery sources** (Workable, Recruitee, Personio boards).
- **Selector regression fixtures**: saved HTML per ATS so selector drift is caught in CI.
- **Weekly report**: response rate per resume variant and per company type.

## Possible (open to a strong PR)

- Discord / Slack adapters mirroring the Telegram commands.
- A local web dashboard for stats.
- "Shadow" mode: email yourself the tailored resume + filled answers instead of submitting.
- Non-English validator support.

## Won't do

- Other LLM providers. Gemini only, for a $0 runtime.
- Bulk applying, or raising the 25/day ceiling.
- LinkedIn application automation.
- Captcha solving services.
- Weakening the validator.
- A hosted SaaS version. Fork it if you want to host it for others.
