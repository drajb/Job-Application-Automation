# Configuration

## Environment variables

All env vars live in `.env`. Copy `.env.example` to `.env` and fill in.

### Required for any meaningful use

| Var | Type | Default | What it does |
|---|---|---|---|
| `GEMINI_API_KEY` | string | — | Gemini 2.5 Flash API key. Free tier at https://aistudio.google.com/apikey. Without it, tailoring + Tier-2 + email classification all disable. |
| `TELEGRAM_BOT_TOKEN` | string | — | From @BotFather. Without it, no approval gate (the agent will not run live). |
| `TELEGRAM_CHAT_ID` | int | — | Your numeric chat ID. Found via `getUpdates` after messaging your bot. Enforced as an allowlist on every command. |

### Required for email monitoring (Phase 3+)

| Var | Type | Default | What it does |
|---|---|---|---|
| `APPLY_EMAIL_USER` | string | — | Dedicated email address for job applications. |
| `APPLY_EMAIL_PASSWORD` | string | — | App password. Enable 2FA on the account first. |
| `APPLY_EMAIL_IMAP_HOST` | string | `imap.gmx.com` | IMAP server hostname. |
| `APPLY_EMAIL_IMAP_PORT` | int | `993` | IMAP server port. SSL on 993, STARTTLS on 143 (not currently supported). |

### Optional

| Var | Type | Default | What it does |
|---|---|---|---|
| `RESUME_SOURCE_DIR` | path | `./resumes` | Where to find your resume variants. Each subfolder is a variant; each contains one or more `.md` files. |
| `BACKUP_DEST` | path | `/mnt/c/Users/$USER/Backups/apply-agent` | Where `scripts/backup.sh` writes nightly tar.gz archives. |

## CLI flags

```bash
python -m src.main [flags]
```

| Flag | Default | Effect |
|---|---|---|
| (none) | — | Polling mode: starts Telegram bot, IMAP listener, scheduler. Runs until Ctrl-C. |
| `--apply <url>` | — | One-shot: tailor + fill the given URL, then exit. |
| `--dry-run` | on | Do not click final Submit anywhere. Safe default. |
| `--no-dry-run` | — | Enable real submissions. **Only use after watching a dry-run.** |
| `--no-telegram` | off | Skip Telegram entirely (log warnings instead of sending). Useful for tests. |
| `--ping` | off | Send "pong" to your Telegram chat and exit. Used to verify the bot is reachable. |

## Make targets

See [README §Make targets](../README.md#make-targets).

## Telegram commands

| Command | What |
|---|---|
| `/ping` | Liveness check. |
| `/apply <url>` | Queue an application. |
| `/pending` | List queued + tailored applications (last 10). |
| `/status` | Today / week submission counts. |
| `/done <app_id>` | Mark an application as Submitted (used after Tier-3 manual takeover). |
| `/profile` | Print the decrypted profile summary. |
| `/passwords` | Print the path to `secrets/portal_passwords.csv`. |

Inline buttons (on the approval card): ✅ Submit, ✗ Reject, 📷 Screenshot, ✏️ Edit, 🖥 Handoff, 🛑 Abort.

## Profile schema

See [src/profile/schema.py](../src/profile/schema.py) for the pydantic source of truth. `profile.example.yaml` is the working template.

## Locked decisions you cannot configure

The following are deliberately not env-var-tunable. To change them, you must edit the spec ([docs/SPEC.md §9](SPEC.md)) and the relevant code. They are locked because changing them invalidates the truthfulness / safety guarantees:

- LLM provider (Gemini only)
- Embeddings model (bge-small-en-v1.5)
- Encryption scheme (`age` only)
- Validator rules (entity-based, no allowlist expansion without a passing test)
- 90-day cooldown
- 25/day hard cap
- `dry_run=True` default
