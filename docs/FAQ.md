# FAQ

## "Is this a bulk applier?"

No, and please don't try to turn it into one. The pre-flight enforces:

- 25 applications/day hard cap
- 90-day cooldown on `(company, role)`
- A configurable submission window (default 10am–6pm CT)

The goal is 15–20 carefully chosen applications per day. The HITL approval gate (mandatory Telegram approval before every submit) makes bulk impractical by design.

## "Will this get me banned from ATSes?"

Tier-1 adapters use Playwright with light stealth, persistent profile, and human-like jitter timing. We've not had reports of bans, but no guarantees. If you're worried:

- Run only Tier-1 (don't pass `--no-dry-run` until you've checked the screenshot)
- Stay under 10 apps/day
- Don't share the dedicated browser profile with your main browsing
- LinkedIn Easy Apply is permanently Tier-3 (manual) for this reason

## "Why Gemini and not Claude / GPT?"

Three reasons:

1. **Free tier with no credit card.** Lowers the barrier to entry for OSS users.
2. **Generous quota.** 1500 RPD covers ~400 RPD worst-case load with headroom.
3. **Vision-capable**. Tier-2 driving uses the same model — no separate VLM.

The locked spec is Gemini-only. PRs adding other providers will be rejected on principle. If you really want to swap, fork and let us know what worked.

## "Why local embeddings instead of an embedding API?"

`bge-small-en-v1.5` runs on CPU in ~200ms on a Pi 5 or any modern laptop. We don't need a network round trip to embed a question, and we don't want to spend Gemini quota on it.

## "Why SQLite instead of Postgres?"

Single-process, single-machine, append-mostly. SQLite + WAL + sqlite-vec is more than enough for ~6000 applications/year. If you outgrow this, congratulations on getting a job and you can stop using the tool.

## "Why Telegram instead of Slack / Discord / push notifications?"

- 1-click bot setup with @BotFather.
- Long polling means no exposed ports on your machine.
- Mobile-first — approvals from the bus.
- Inline keyboard buttons are easy and reliable.

PR for a Discord/Slack adapter welcome.

## "Does the validator catch everything?"

No. It catches **blatant fabrication** — invented employers, years that aren't in the source, tools you didn't list. It does NOT catch:

- Subtle paraphrase that drifts in meaning ("led a team of 4" → "managed a team of 8")
- Skill claims at a level you don't have
- Rewording achievements in a way that's technically true but misleading

That's why every submit goes through your manual approval. The validator is the first line; you are the second.

## "Validator rejected my legitimate resume. Help."

Likely cause: your source resume `.md` is so short there aren't enough entities to anchor on, so any new word looks like fabrication.

Fix: enrich your source resume. Specifically, include:

- Full employer names (not abbreviations)
- All graduation years
- Every tool/framework you've actually used (in a SKILLS section)
- Locations

If after that you still get false positives, please open an issue with a minimal repro. Do not weaken the validator — add it to the test suite so we can fix it together.

## "Can I run this on a Raspberry Pi?"

Yes, a Pi 5 with 16GB works. You'll need:

- ARM64 Chromium (Playwright supports it)
- ARM64 `age` binary (compile or grab from a release)
- LibreOffice headless (slow on Pi)
- bge-small inference (slow but functional)

Expect ~2-3 minute first-call latency for the embedding model load. After that, normal.

## "Can I run multiple instances?"

You can, but you'd be applying as multiple identities, which is misleading. Don't do that.

If you mean "can I have a dev and a prod instance" — yes, but use separate `secrets/`, `data/`, and DB paths. The simplest way is two checkouts in different directories with different `RESUME_SOURCE_DIR` env vars.

## "Why is there a 10am-6pm submission window?"

Recruiters check applications during work hours. Applications submitted at 3am can look low-effort. We default to CT because the developer's timezone is CT; override with the config or remove the check if you don't care.

## "Why 90-day cooldown?"

Recruiters get annoyed when the same person re-applies for the same role 4 times in a week. We pick 90 days because that's roughly how long postings stay open. If a role re-opens after 90 days, that's a meaningful signal.

## "Can the agent send follow-up emails?"

Not currently, and we're cautious about adding it. The risk of looking robotic is high. If you want this, open an issue with a specific use case.

## "Why two retries on validator failure?"

Empirically, Gemini Flash regenerates with feedback ~70% of the time. Three retries was barely better and burned quota. Hard escalation is fine — you'll be in Telegram approving anyway.

## "Does this work for non-English JDs?"

Untested. Gemini handles ~50 languages so the tailor should work. The selectors are language-agnostic (they're CSS classes, not text). The validator's entity regexes assume ASCII years and capitalized phrases. Open an issue if you try this.

## "I want to contribute. Where do I start?"

[CONTRIBUTING.md](../CONTRIBUTING.md), then look at issues labeled `good first issue`. Selector decay fixes are always welcome.

## "Can I use this without Telegram?"

Yes, run with `--no-telegram` and use the CLI `--apply <url>` mode. You'll lose the approval gate, so we strongly recommend keeping `--dry-run` on and reviewing PDFs + screenshots manually.

## "Is there a Web UI?"

No, and not on the roadmap. Telegram is the UI.
