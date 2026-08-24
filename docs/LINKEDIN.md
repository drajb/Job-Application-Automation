# LinkedIn

LinkedIn is intentionally constrained in this project:

1. **Easy Apply is Tier-3 manual takeover only.** The agent will open the JD in a real Chromium window with your saved session, alert you on Telegram, and exit. You finish the form yourself. There is no automatic Apply click, no automatic form fill, no automatic submit. This is a permanent rule.
2. **Referral scan is read-only.** The agent will list your 1st-degree connections at a target company so you can pick one to reach out to. It does NOT send connection requests, DMs, or InMail.
3. **DM drafter is a draft assistant.** The agent uses Gemini to draft a short DM. You paste and send it yourself.

## Why so cautious?

LinkedIn's bot detection is aggressive, and a wrongful flag can permanently lock your account — the same account you use for the actual job search. The risk-reward of automation here is awful. The agent helps you prepare; you do the touchy parts.

## Saving a session

The agent reads `secrets/linkedin/storage_state.json` (override with `LINKEDIN_SESSION_PATH`). To save one:

```bash
python -m scripts.save_linkedin_session
```

This launches a headed Chromium window. Log in normally (yes, including 2FA), wait until you see your LinkedIn home feed, then press Enter in the terminal. The script writes the storage state to disk and exits.

Re-run the script every couple of months — `li_at` cookies age out.

## What the referral scanner sees

When you run `/scout-linkedin <company>` (Phase 7+), the agent:

1. Opens `https://www.linkedin.com/search/results/people/?keywords=<company>&network=%5B%22F%22%5D` (1st-degree connections at that company).
2. Scrolls a few times to load results.
3. Extracts up to 20 names + headlines + profile URLs.
4. Ranks them: recruiter +10, leadership +6, individual contributor +3, name-match +5.
5. Returns the list.

No actions, no clicks beyond the scroll. The whole flow is read-only.

## What the DM drafter sees

The drafter receives only:
- The candidate's `name`, `headline`, `profile_url`.
- The target `company` and `role`.
- Your `legal_name` from the encrypted profile.
- Free-text "common ground" you supply (optional).

It returns a 60–110 word DM string. You read it, edit if you want, and paste into LinkedIn yourself.

## What if I want full automation?

You don't. Get a referral or use a real ATS. That's the answer.
