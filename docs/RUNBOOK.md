# Runbook

Concrete, do-this-now steps. The recommended deployment is WSL2 Ubuntu on a Windows host (this is what the project was developed against), but any Linux box with Python 3.11+ works.

---

## One-time setup

### 1. WSL2 systemd (Windows hosts only)

```bash
# inside WSL Ubuntu
echo -e "[boot]\nsystemd=true" | sudo tee /etc/wsl.conf
# then in Windows PowerShell:
wsl --shutdown
# reopen Ubuntu; systemd is now PID 1
```

Skip this step on a native Linux box.

### 2. OS packages

```bash
sudo apt update
sudo apt install -y \
  build-essential libffi-dev libssl-dev \
  libreoffice --no-install-recommends \
  age \
  python3.11 python3.11-venv python3-pip
```

LibreOffice renders the tailored markdown → PDF. `age` is the encryption tool.

### 3. Chromium for Playwright

```bash
sudo apt install -y chromium-browser  # or use Playwright's own download
```

Or after `make dev-install`:

```bash
.venv/bin/python -m playwright install chromium
```

On Windows + WSLg, launching headed Chromium from WSL pops the window onto your Windows desktop. On native Linux you need a display server.

### 4. Power settings (Windows host)

Settings → System → Power → "When plugged in, PC goes to sleep" → **Never**. The display can sleep; the machine cannot, or WSL will be paged out.

### 5. Auto-launch on login (Windows)

Open Task Scheduler → Create Basic Task:

- Trigger: At log on
- Action: Start a program
- Program: `wsl.exe`
- Arguments: `-d Ubuntu -- bash -lc 'cd ~/apply-agent && make run >> ~/apply-agent.log 2>&1'`

Skip until you've verified a few dry-runs work.

### 6. Clone + install

```bash
git clone https://github.com/drajb/Job-Application-Automation.git ~/apply-agent
cd ~/apply-agent
make dev-install
```

### 7. Generate the master encryption key

```bash
make keygen
```

This creates `secrets/master.age.key`. **Back it up immediately** to:

- 1Password, Bitwarden, or your password manager of choice (paste the file contents into a secure note), and
- a USB drive or other external location.

If you lose this file, you lose every portal password the vault ever stores. There is no recovery.

### 8. Email provider setup

Pick an email account dedicated to job applications. Do **not** reuse your main personal email — the agent will mark messages Seen and trigger Telegram alerts.

| Provider | IMAP host | Port | App password? |
|---|---|---|---|
| GMX | `imap.gmx.com` | 993 SSL | Recommended |
| Outlook.com | `outlook.office365.com` | 993 SSL | Required if 2FA on |
| Gmail | `imap.gmail.com` | 993 SSL | Required |
| Proton Mail | `imap.proton.me` | 1143 (via Bridge) | Required (Bridge) |
| FastMail | `imap.fastmail.com` | 993 SSL | Required |

Enable 2FA on the account, then generate an app password. Add to `.env`:

```
APPLY_EMAIL_USER=youraddress@example.com
APPLY_EMAIL_PASSWORD=<app-password>
APPLY_EMAIL_IMAP_HOST=imap.your-provider.com
APPLY_EMAIL_IMAP_PORT=993
```

### 9. Gemini API key

1. Visit https://aistudio.google.com/apikey
2. "Create API key" → free tier, no credit card.
3. Add to `.env`:
   ```
   GEMINI_API_KEY=AIza...
   ```

Free-tier limits: 15 RPM / 1500 RPD / 1M TPM. Worst-case load is ~400 RPD for a full day of 15-20 applications.

### 10. Telegram bot

1. In Telegram, DM `@BotFather`.
2. Send `/newbot`. Choose a name and username. Copy the bot token.
3. Send any message to your new bot from your personal Telegram account.
4. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser. Find `"chat":{"id":<NUMBER>` — that's your chat_id.
5. Add to `.env`:
   ```
   TELEGRAM_BOT_TOKEN=<token>
   TELEGRAM_CHAT_ID=<chat_id>
   ```

### 11. Profile

```bash
cp profile.example.yaml secrets/profile.yaml
$EDITOR secrets/profile.yaml
```

Fill in your details. Most fields map 1:1 to ATS form fields:

- `identity.*` → name, email, phone, location, social URLs
- `work_authorization.*` → sponsorship questions, current status
- `demographics.*` → optional disclosure fields (gender, race, veteran, disability)
- `compensation.*` → desired salary band, notice period, start date
- `background.*` → felony, citizenship, clearance, "how did you hear"
- `education[].*` → degree, institution, grad year
- `essays.*` → templates for why-company / why-role / about-me / proud-project

Then encrypt:

```bash
make encrypt-profile     # encrypts to secrets/profile.yaml.age, deletes plaintext
```

### 12. Resumes

Drop one subfolder per role variant into `resumes/` (or wherever you point `RESUME_SOURCE_DIR`):

```
resumes/
  master/
    Resume_v1.md
    Resume_v1.docx
  staff-engineer/
    Resume_v1.md
  engineering-manager/
    Resume_v1.md
```

The selector routes by JD keywords (manager / director / lead / staff / pm / researcher / ...) to the closest folder, then cosine-ranks the `.md` files inside. **Source resumes are never modified.** Tailored output lands in `data/tailored/<uuid>.pdf`.

### 13. Migrations + smoke

```bash
make migrate          # creates apply_agent.db with all schema
make test             # pytest, all green
make run              # starts Telegram bot + IMAP + scheduler
make ping             # one-shot Telegram test
```

If `make ping` posts "pong — apply-agent alive." to your Telegram, setup is done.

---

## Daily operations

| From Telegram | What |
|---|---|
| `/apply <url>` | Queue an application. Approval card arrives in 30–90s. |
| `/pending` | List queued + tailored applications. |
| `/status` | Today + this week submission counts, response rate, Gemini RPD used. |
| `/done <app_id>` | Manually mark an application as Submitted (used after Tier-3 takeover). |
| `/profile` | Print the decrypted profile (redacted to chat). |
| `/passwords` | Print path to the password CSV mirror. |
| `/ping` | Liveness check. |

---

## Backup

Nightly `tar.gz` of `secrets/`, `data/`, and the DB to a local backup path. Add to cron inside WSL/Linux:

```cron
0 3 * * * /home/<user>/apply-agent/scripts/backup.sh >> /tmp/apply-backup.log 2>&1
```

Set `BACKUP_DEST` in the environment to override the default. Retains the last 30 archives.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "telegram disabled" on startup | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` missing | Fill `.env`, restart |
| Validator rejects every tailored output | Source resume sparse → no entities to anchor on | Use the `master/` variant; add a richer resume |
| Browser pops up but does nothing | No `GEMINI_API_KEY` → Tier-2 falls back to wait | Add the key to `.env` |
| "outside submission window" all the time | Configured timezone wrong | Set `SUBMIT_TIMEZONE` in `.env` (default `America/Chicago`) |
| IMAP fails to connect | Provider needs an app password | Enable 2FA, generate app password, replace `APPLY_EMAIL_PASSWORD` |
| Validator passes but resume reads wrong | Likely fine — validator catches fabrication, not style. Edit the source resume `.md` and rerun. |
