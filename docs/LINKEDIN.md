# LinkedIn

LinkedIn is deliberately limited:

1. **No automated applying.** Any LinkedIn URL passed to `/apply` (including `linkedin.com/comm/...` and `lnkd.in` short links) is refused with a "manual only" message. Apply on LinkedIn yourself.
2. **Referral scan is read-only** (library code in `src/linkedin/referral_scan.py`, not wired to a command yet). It lists 1st-degree connections at a company from your saved session. It sends nothing.
3. **DM drafter is a draft assistant** (`src/linkedin/dm_drafter.py`). It writes a short message from the person's headline and the facts you pass in (your name and current role). You edit and send it yourself.

## Why so cautious?

LinkedIn's bot detection is aggressive and a flag can lock the account you're job-hunting with. Scraping with a logged-in session can also break LinkedIn's terms, so use the referral scan sparingly or not at all.

## Saving a session (only needed for the referral scan)

```bash
python -m scripts.save_linkedin_session
```

Log in in the window that opens (including 2FA), wait for your feed, press Enter. The session is saved to `secrets/linkedin/storage_state.json` (override with `LINKEDIN_SESSION_PATH`). It's a login cookie, so treat it like a password; it expires every few months.
