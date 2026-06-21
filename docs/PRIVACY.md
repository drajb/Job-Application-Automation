# Privacy

## What data this tool stores, and where

| Data | Where | Encrypted at rest? | Sent over the wire? |
|---|---|---|---|
| Your profile (name, contact, comp expectations, demographics, essays) | `secrets/profile.yaml.age` | ✅ age | Pieces flow into Gemini prompts when you tailor or generate an essay. |
| Portal credentials (per-site usernames + passwords) | `apply_agent.db:portal_credentials.password_enc` + CSV mirror | ✅ age (DB blob); ⚠️ plaintext in the CSV mirror | No (credentials only typed into the portal's own login form) |
| Master encryption key | `secrets/master.age.key` | ❌ (it IS the key) | No, never. |
| Source resumes | `RESUME_SOURCE_DIR` (default `./resumes/`) | ❌ | Whole resume body is sent to Gemini during tailoring. |
| Tailored PDFs | `data/tailored/` | ❌ | Uploaded to each ATS as the resume attachment. |
| Application history | `apply_agent.db:applications` | ❌ | No. |
| Q&A learned answers | `apply_agent.db:qa_log` | ❌ (embedding + plaintext) | Question embeddings are local. Answers are sent to Gemini during rephrase. |
| Email response excerpts | `apply_agent.db:response_log` | ❌ | Email body is sent to Gemini for classification. |
| Screenshots | `data/screenshots/` | ❌ | Sent to Telegram on handoff. |
| Browser cookies | `chrome-profile-apply/` | OS-dependent | Sent to whatever portal set them. |

## What gets sent to Google (Gemini)

Every Gemini call sends:

- The full prompt (system + JD + relevant resume bullets + question).
- The model's response.

What's in those prompts:

- **Tailor calls** (`src/llm/prompts/tailor.py`): the full JD + the full source resume + company + role.
- **Email classifier** (`src/email_monitor/classifier.py`): the from address, subject, and first 2000 chars of the email body.
- **Tier-2 driver** (`src/execution/tier2_browseruse.py`): a stripped text snapshot of the current page (first 6000 chars) plus the task description.
- **Q&A rephrase** (`src/profile/qa_log.py`): the new question + the prior answer + company + role.

Google's [Gemini API privacy policy](https://ai.google.dev/gemini-api/terms) governs what they do with this. As of the time of writing, the free tier is used for model improvement; the paid tier is not. **If you do not want your prompts used for training, switch to a paid Gemini key** and the agent will continue to work — same SDK, same model, same code.

## What gets sent to OpenAI, Anthropic, or any other provider

**Nothing.** The agent only calls Google's Gemini API. It does not have, will not gain, and will not accept code to call any other LLM provider.

## What gets sent to Telegram

- Every approval card (company + role + ATS + variant + resume UUID).
- Every response alert (sender, subject, first 600 chars of body).
- Every handoff card (screenshot).
- Every `/profile` invocation (decrypted profile summary).

Telegram bot messages are end-to-end-encrypted between client and server, but not E2EE between you and yourself — Telegram has them on their servers. If this matters, run a [private Telegram MTProxy](https://core.telegram.org/mtproto/mtproto-transports#mtproxy) or switch to a self-hosted Matrix bridge (PRs welcome).

## What gets sent to your inbox provider

- Standard IMAP IDLE: connection, INBOX folder reads, `\Seen` flag updates.
- No outbound mail. The agent does not send replies, follow-ups, or DMs from your inbox.

## What gets sent to ATSes and company sites

- Whatever the form requires: your profile fields, the tailored resume PDF, free-text essay answers, custom-question answers from `qa_log`.
- During Tier-2 the agent fetches the JD page; during company research the agent fetches the company homepage + `/about` + `/news` pages with a custom UA string identifying this tool.

## What gets sent to GitHub (or anywhere else)

**Nothing.** No analytics. No crash reporting. No "phone home" of any kind.

## What's in your git history

If you follow the recommended `.gitignore` (and you should — it's already configured):

- `secrets/` is not tracked.
- `*.db`, `*.age.key`, `.env`, `chrome-profile-apply/`, `profile.yaml`, `data/tailored/` are not tracked.

If you do `git status` and see any of those listed as untracked or modified, do not commit. Open an issue if the gitignore should be tightened.

## Deleting yourself

```bash
rm -rf secrets/ data/ chrome-profile-apply/ apply_agent.db .env
```

That removes every piece of state this tool has accumulated about you. Done.

You may also want to:

- Revoke your Gemini API key at https://aistudio.google.com/apikey.
- Revoke your bot at @BotFather (`/deletebot`).
- Reset your email app password at your provider.
- For each portal account the agent created, log in once via the portal's password-reset flow and delete the account if the portal supports it.
