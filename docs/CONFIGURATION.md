# Configuration

All settings are environment variables, normally kept in `.env` (copy `.env.example`). `.env` is read from the repo root; real environment variables win over it. Check your setup any time with `make doctor`.

## Credentials

| Var | Default | What it does |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini key, free at https://aistudio.google.com/apikey. Needed to tailor resumes and drive Tier-2 forms. Without it, email classification falls back to keyword rules. |
| `TELEGRAM_BOT_TOKEN` | — | From @BotFather. Needed for approvals; real submissions are refused without it. |
| `TELEGRAM_CHAT_ID` | — | Your numeric chat ID (from `getUpdates` after messaging your bot). Every command, button and reply is checked against it. Use a private chat, not a group. |
| `APPLY_EMAIL_USER` | — | A dedicated job-search mailbox. Enables response alerts and account sign-up verification. |
| `APPLY_EMAIL_PASSWORD` | — | App password for that mailbox (turn on 2FA first). |
| `APPLY_EMAIL_IMAP_HOST` | `imap.gmx.com` | IMAP-over-SSL host. |
| `APPLY_EMAIL_IMAP_PORT` | `993` | IMAP-over-SSL port. STARTTLS-only servers (e.g. Proton Bridge on 1143) aren't supported. |

## Paths

Relative paths resolve against the repo root, not the current directory.

| Var | Default | What it does |
|---|---|---|
| `RESUME_SOURCE_DIR` | `./resumes` | Your resumes: one subfolder per variant, each with `.md` files. Files with `example` in the name are ignored. |
| `APPLY_AGENT_DB` | `./apply_agent.db` | SQLite database. |
| `WATCHLIST_PATH` | `./watchlist.yaml` | Companies and filters for job discovery. |
| `APPLY_BROWSER_PROFILE` | `./chrome-profile-apply` | The agent's own browser profile (cookies, logins). Never your everyday profile. |
| `GEMINI_USAGE_FILE` | `./data/gemini_usage.json` | Where today's Gemini request count is kept across restarts. Empty = don't persist. |
| `BACKUP_DEST` | `~/backups/apply-agent` | Where `make backup` writes archives. |

## Guardrails

These can only be made **stricter**. The 25/day cap can be lowered, not raised.

| Var | Default | Range | What it does |
|---|---|---|---|
| `APPLY_TIMEZONE` | `America/Chicago` | IANA name | Timezone for the submission window, daily cap, digest and scan schedule. |
| `SUBMIT_WINDOW_START` | `10` | 0–23 | Earliest hour (local) a submission may happen. |
| `SUBMIT_WINDOW_END` | `18` | 1–24 | Submissions stop at this hour. |
| `DAILY_CAP` | `25` | 1–25 | Max submissions per local day. |
| `COOLDOWN_DAYS` | `90` | 30–3650 | Won't re-apply to the same (company, role) within this many days. |

## Runtime

| Var | Default | What it does |
|---|---|---|
| `GEMINI_RPM` / `GEMINI_RPD` | `10` / `250` | Your Gemini free-tier limits. Google changes these — check https://ai.google.dev/gemini-api/docs/rate-limits. New applications pause at 80% of RPD; email classification may use up to 100%. |
| `SCAN_HOUR` | `9` | Hour (local) of the daily watchlist scan when the daemon runs with Telegram. `off` disables it. |
| `APPLY_HEADLESS` | off | `1` runs the browser without a window (Docker/servers). Tier-3 takeover needs a window. |

## CLI

```bash
python -m src.main [flags]
```

| Flag | Effect |
|---|---|
| (none) | Daemon: Telegram bot + inbox monitor + scheduler. Dry-run. |
| `--no-dry-run` | Allow real submissions. Each one still needs your Telegram approval; refused without Telegram. |
| `--no-telegram` | Run without the bot (inbox monitor + scheduler only). |
| `--apply URL` | One application, then exit. |
| `--scan [--all]` | Scan your watchlist, print a ranked table. `--all` includes roles you've already seen. |
| `--fit URL_OR_FILE` | Fit score + which JD keywords your resume has / lacks. No LLM. |
| `--doctor [--offline]` | Check every prerequisite and say how to fix what's missing. |
| `--done ID` | Record an application you finished by hand. |
| `--export PATH` | Write your applications to CSV. |
| `--ping` | Send a test message to Telegram. |
| `-v` | Debug logging. |

## Telegram commands

| Command | What |
|---|---|
| `/apply <url>` | Tailor, fill, screenshot, ask for approval. Runs one at a time. |
| `/scan` | Scan your watchlist; each new role arrives with 🚀 Apply / 🙈 Skip buttons. |
| `/pending` | Applications waiting on you. |
| `/status` | Today / week submissions, responses, Gemini usage. |
| `/done <id>` | You finished one manually. |
| `/abort <id>` | Stop an in-flight application. |
| `/profile` | Redacted profile summary. |
| `/passwords` | Where the password CSV mirror lives (on the agent's machine). |
| `/help` | This list. |

Buttons on the approval card: **✅ Submit** (or **Looks good** in dry-run), **✗ Reject**, **🖥 Take over**. On a question: reply to the message with the answer, or **⏭ Skip / 🖥 Take over / 🛑 Abort**.

## Profile

[src/profile/schema.py](../src/profile/schema.py) is the source of truth; `profile.example.yaml` is the template. Edit an encrypted profile with `make edit-profile`, then `make encrypt-profile`.

## Not configurable

Changing these would break the truthfulness or safety guarantees ([docs/SPEC.md](SPEC.md)):

- LLM provider (Gemini only) and the local embedding model
- `age` encryption
- The validator's rules
- `dry_run=True` default, approval before every submit
- The 25/day ceiling and the 30-day cooldown floor
