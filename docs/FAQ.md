# FAQ

## Is this a bulk applier?

No. It enforces a daily cap (25, lower if you set `DAILY_CAP`), a 90-day cooldown per (company, role), a submission window, and your approval before every submit. The goal is a handful of well-matched applications a day.

## Will it lie on my resume?

The tailor may reword, reorder and trim. The validator rejects any draft that adds an employer, title word, year, number, tool, URL or email that isn't in your source resume, or that drops roles or gets cut off. After two rejected attempts it stops and tells you what it tried to add.

It can't catch everything: moving a real tool to a different job, or a rewording that shifts meaning while using only your words. That's why the approval card shows bullet-by-bullet diffs. You are the last check.

## The validator rejected my draft. What do I do?

The Telegram message lists the flagged items. If they're true, add them to your source resume (the tailor won't add facts for you). If a flag looks wrong (for example a common word), open an issue with the snippet. Please don't loosen the validator in a fork you share.

## Will this get me banned from job sites?

It uses a dedicated browser profile, human-like pacing, a daily cap, and one application at a time. Captchas and anything unusual go to you instead of being bypassed. LinkedIn is never automated. No guarantees, but it behaves like a careful person.

## Why Gemini?

A free tier with no credit card, which keeps the runtime at $0. It's the only provider by design. Free-tier limits change, so set `GEMINI_RPM` / `GEMINI_RPD` to what AI Studio shows you. Tailoring uses about 1–3 requests per application; Tier-2 forms use more (one per step).

## Why Telegram?

Five-minute setup, no open ports (long polling), and approvals from your phone. Discord/Slack adapters would be welcome PRs.

## Can I use it without Telegram?

For dry runs, yes: `python -m src.main --apply <url>` fills the form and saves a screenshot without submitting. Real submissions require Telegram, because every one needs your approval.

## How does job discovery work?

You list companies in `watchlist.yaml` (Greenhouse, Lever, Ashby or SmartRecruiters board slugs) plus title/location filters. `/scan` or `make scan` reads their public job feeds, scores each role against your resumes (keyword coverage + local embeddings, no LLM calls), and shows the new ones with the keywords you're missing. It only suggests; you choose what to apply to.

## Does it handle visa / sponsorship questions correctly?

"Will you require sponsorship?" and "Are you authorized to work without sponsorship?" are answered from your profile with the correct yes/no for each wording. Other sensitive questions (criminal history, clearance, legal, salary when your profile has no figure) are asked to you, and a saved answer is reused only for the same exact question.

## Can I run it on a Raspberry Pi or a server?

Yes. The Docker image runs headless (`APPLY_HEADLESS=1`). Embedding and LibreOffice are slower on a Pi but work. Tier-3 handoffs need a desktop to take over the browser; on a server you'll be told to finish those on your own machine.

## Which timezone does it use?

`APPLY_TIMEZONE` (default `America/Chicago`). The submission window, daily cap, digest and scan times all follow it.

## Does it work for non-English postings?

Untested. Gemini handles many languages, but the validator and question classifier assume English text.

## Does it send follow-up emails or LinkedIn messages?

No. It drafts LinkedIn DMs on request; you send them.

## How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md). New ATS adapters, selector fixes and validator test cases are the most useful.
