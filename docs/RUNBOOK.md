# Runbook

Running the agent day to day: always-on setup, inbox alerts, backups, troubleshooting. For first-time setup see [QUICKSTART.md](QUICKSTART.md).

The agent runs on any Linux box, macOS, or WSL2 on Windows. Applications need a desktop for the browser window if you want Tier-3 "take over" handoffs; the Docker image runs headless.

---

## Host setup

### OS packages (Ubuntu / Debian / WSL2)

```bash
sudo apt update
sudo apt install -y python3-venv make git age libreoffice-writer-nogui
```

`make browsers` (part of `make setup`) installs Playwright's own Chromium. Don't use the `chromium-browser` snap.

### WSL2 on Windows

- Keep the repo **inside** the Linux filesystem (`~/apply-agent`), not on `/mnt/c`. It's much faster, and file permissions on `secrets/` (0600/0700) are only enforced there.
- WSLg shows the agent's browser window on your Windows desktop.
- Power: Settings → System → Power → "When plugged in, PC goes to sleep" → **Never** (the display can sleep).
- Auto-start: Task Scheduler → Create Basic Task → At log on → Program `wsl.exe`, arguments
  `-d Ubuntu -- bash -lc 'cd ~/apply-agent && make run >> ~/apply-agent/logs/agent.log 2>&1'`
  (create `logs/` first). Do this only after a few dry runs look right.

### Linux with systemd

```ini
# ~/.config/systemd/user/apply-agent.service
[Unit]
Description=apply-agent
After=network-online.target

[Service]
WorkingDirectory=%h/apply-agent
ExecStart=%h/apply-agent/.venv/bin/python -m src.main
Restart=on-failure

[Install]
WantedBy=default.target
```

```bash
systemctl --user enable --now apply-agent
loginctl enable-linger "$USER"   # keep it running after you log out
```

### Docker

```bash
docker compose up -d                       # builds locally, or use the published image:
# image: ghcr.io/drajb/job-application-automation:latest
```

`./secrets`, `./resumes` (read-only) and `./data` are mounted; the DB, browser profile and model cache live in `./data`. The container runs as UID 1000. Browsers are headless, so Tier-3 handoffs tell you to finish on your own machine.

---

## Inbox monitoring

Use a mailbox dedicated to job applications, not your personal one. The agent reads INBOX and marks processed mail as read.

| Provider | `APPLY_EMAIL_IMAP_HOST` | Port | Notes |
|---|---|---|---|
| GMX | `imap.gmx.com` | 993 | App password recommended |
| Outlook.com | `outlook.office365.com` | 993 | App password if 2FA is on |
| Gmail | `imap.gmail.com` | 993 | App password required |
| Fastmail | `imap.fastmail.com` | 993 | App password required |

Proton Mail Bridge (STARTTLS on 1143) isn't supported.

What happens to each email:

- **Verification emails** for portal sign-ups are matched to the waiting sign-up: the sender must be the portal's domain (or a subdomain), DKIM must pass when the server records it, and the link must point at that domain.
- **Interview invites, recruiter outreach, offers** → an immediate Telegram alert with the excerpt and the matching application (company, role, days since you applied, which resume variant).
- **Rejections and other mail** → logged, listed in the 7pm digest.
- Without a Gemini key (or when the daily quota is used up) classification falls back to keyword rules.
- A message that fails to process stays unread and is retried (up to 3 times).

---

## Daily use

| Telegram | What |
|---|---|
| `/apply <url>` | One application. You get the filled-form screenshot + approval card. |
| `/scan` | New roles from your watchlist, each with 🚀 Apply. Also runs daily at `SCAN_HOUR`. |
| `/pending` | What's waiting on you (handoffs, unverified submits, deferred). |
| `/status` | Today / week numbers and Gemini usage. |
| `/done <id>`, `/abort <id>` | Finish or stop an application. |

The 7pm digest summarises submissions, responses, quiet mail and your best-performing resume variant.

---

## Backups

`make backup` (or `scripts/backup.sh`) writes `apply-agent_<timestamp>.tar.gz` with `secrets/`, `data/` and a consistent snapshot of the DB to `BACKUP_DEST` (default `~/backups/apply-agent`), keeping the last 30. The archive contains your master key and the plaintext password CSV, so it's created 0600; keep `BACKUP_DEST` private (not a shared or cloud-synced folder unless it's encrypted).

```cron
0 3 * * * cd /home/<you>/apply-agent && bash scripts/backup.sh >> /tmp/apply-backup.log 2>&1
```

Also keep a separate copy of `secrets/master.age.key` in your password manager. Without it the vault can't be decrypted.

---

## Troubleshooting

Start with `make doctor`. It checks resumes, database, profile, Gemini key, LibreOffice, Chromium, watchlist, Telegram and IMAP, and says how to fix each.

| Symptom | Likely cause | Fix |
|---|---|---|
| "outside submission window" | Window is in `APPLY_TIMEZONE` (default America/Chicago) | Set `APPLY_TIMEZONE`, `SUBMIT_WINDOW_START/END` |
| "Gemini daily quota" / deferred applications | Free tier exhausted | Waits for the midnight-Pacific reset. Set `GEMINI_RPD` to your real limit |
| Validator rejects every draft | The draft keeps adding something not in your resume | The Telegram message lists the flagged items. If they're true, add them to your source resume |
| "no valid resume PDF" on a live run | LibreOffice missing | `sudo apt install libreoffice-writer-nogui` |
| "real submissions need Telegram approval" | `--no-dry-run` without Telegram | Configure Telegram, or stay in dry-run |
| "this portal needs an account" | Tier-2 site wants a login | Run live with the vault + inbox set up (it signs up for you), or sign in once yourself in the agent's browser profile |
| IMAP login fails | Provider wants an app password | Enable 2FA, create an app password |
| Clicked Submit but "no confirmation detected" | The ATS showed an unusual confirmation | Check the after-submit screenshot and your inbox; `/done <id>` if it went through |
