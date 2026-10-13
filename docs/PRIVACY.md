# Privacy

## What is stored, and where

| Data | Where | Encrypted at rest? | Leaves your machine? |
|---|---|---|---|
| Profile (name, contact, work authorization, salary, demographics) | `secrets/profile.yaml.age` | ✅ age | Name/contact/education go to Gemini as validator context; answers go to the ATS forms you approve. Salary is never sent to Gemini. |
| Portal passwords | `apply_agent.db:portal_credentials` | ✅ age per row | Only typed into that portal. Never sent to Gemini (the LLM types a placeholder). |
| Password CSV mirror | `secrets/portal_passwords.csv` | ❌ plaintext, 0600 | No |
| Master key | `secrets/master.age.key` | ❌ (it is the key), 0600 | No |
| Source resumes | `RESUME_SOURCE_DIR` | ❌ | Sent to Gemini for tailoring |
| Tailored resumes | `data/tailored/` | ❌ | Uploaded to the ATS you approve |
| Applications, learned answers, email excerpts, discovered jobs | `apply_agent.db` | ❌ | Learned answers may go to Gemini when adapting a long answer |
| Screenshots | `data/screenshots/` | ❌ | Sent to your Telegram chat |
| Browser cookies | `chrome-profile-apply/` | ❌ | To the sites that set them |
| Backups | `BACKUP_DEST` | ❌ (0600) | No |
| Training proposals | `data/training_proposals_*.md` | ❌ | No |

File permissions (0600/0700) are only enforced on a Linux/macOS filesystem. On WSL keep the repo under `~`, not `/mnt/c`.

## What goes to Google (Gemini)

- **Tailoring:** the job description, your source resume, company and role.
- **Tier-2 forms:** a text snapshot of the form page and your basic answers (name, contact, links, work-authorization yes/no). Not salary, not passwords.
- **Job parsing (Tier 2):** the posting's page text.
- **Email classification:** sender, subject and the first 2000 characters of the body.
- **Answer adaptation:** a previous long answer and the new question.

On the free tier Google may use prompts to improve its models ([terms](https://ai.google.dev/gemini-api/terms)). A paid key avoids that, with the same code.

**No other AI provider is ever called.**

## What goes to Telegram

Approval cards (company, role, tailored-bullet diffs), screenshots of filled forms, questions you're asked, response alerts (sender, subject, first 600 characters), the digest. `/profile` shows a redacted summary. Bot messages are encrypted in transit but stored on Telegram's servers (bots can't use secret chats).

## What goes to your inbox provider

IMAP reads of INBOX and the `\Seen` flag on processed messages. The agent never sends email.

## What goes to job boards

Discovery reads public job-board feeds (`boards-api.greenhouse.io`, `api.lever.co`, `api.ashbyhq.com`, `api.smartrecruiters.com`) for the companies in your watchlist. No personal data is sent. ATS forms get exactly what you approve.

## Analytics

None. No telemetry, crash reporting or phone-home.

## Deleting everything

```bash
rm -rf secrets/ data/ chrome-profile-apply/ apply_agent.db .env watchlist.yaml logs/
rm -rf "${BACKUP_DEST:-$HOME/backups/apply-agent}"
rm -rf ~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5   # embedding model
```

Then revoke your Gemini key, delete the bot via @BotFather (`/deletebot`), reset your inbox app password, and delete any portal accounts the agent created (they're listed in the password CSV before you delete it).
