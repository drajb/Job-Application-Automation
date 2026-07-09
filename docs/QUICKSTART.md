# Quickstart — your first dry-run application in 30 minutes

This guide assumes a fresh WSL2 Ubuntu (or any Linux) install with `git` and `make` available.

## 1. Get the code (2 min)

```bash
git clone https://github.com/drajb/Job-Application-Automation.git ~/apply-agent
cd ~/apply-agent
make dev-install
```

`make dev-install` installs Python, pytest, ruff, and ~130 runtime dependencies. The torch + sentence-transformers transitive deps make this ~3 minutes on a fast connection.

## 2. Get a Gemini API key (2 min)

1. Visit https://aistudio.google.com/apikey
2. "Create API key" — free tier, no credit card.
3. Copy the `AIza...` string.

## 3. Get a Telegram bot (3 min)

1. DM `@BotFather` in Telegram, send `/newbot`.
2. Pick a name and username for your bot.
3. Copy the token (`123456:abc...`).
4. Send any message to your new bot from your personal account.
5. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser. Find the number in `"chat":{"id": <NUMBER>`. That's your chat_id.

## 4. Configure `.env` (1 min)

```bash
cp .env.example .env
```

Open `.env` and paste in:

```
GEMINI_API_KEY=AIza...
TELEGRAM_BOT_TOKEN=123456:abc...
TELEGRAM_CHAT_ID=<your number>
```

Leave the email vars blank for now — the inbox monitor is optional.

## 5. Generate your encryption key (1 min)

```bash
make keygen
```

You'll see a path like `secrets/master.age.key`. **Open the file, copy its contents, paste into your password manager as a secure note.** If you lose this file, all vault passwords are gone.

## 6. Build your profile (10 min)

```bash
cp profile.example.yaml secrets/profile.yaml
$EDITOR secrets/profile.yaml
```

The example file is heavily commented. The fields you must fill:

- `identity.legal_name`, `email`, `phone`, `location`
- `work_authorization.requires_sponsorship`, `current_status`
- `compensation.desired_base_min`, `desired_base_target`
- `education[].degree`, `institution`, `grad_year`

Then encrypt:

```bash
make encrypt-profile
```

This encrypts `profile.yaml` to `profile.yaml.age` and **deletes the plaintext**. You can re-edit later by reversing the process (decrypt with `pyrage`, edit, re-encrypt).

## 7. Add a resume (3 min)

Drop a Markdown resume into `resumes/master/`:

```bash
mkdir -p resumes/master
$EDITOR resumes/master/Resume_v1.md
```

The format is plain Markdown — `# Name`, `## Section`, `- Bullet`. The validator parses entities from this file, so include real employer names, years, and tool names. **Whatever's in this file is the ground truth the tailor is allowed to rephrase.**

If you have multiple variants, add `resumes/staff-engineer/`, `resumes/engineering-manager/`, etc. The selector auto-discovers them.

## 8. Migrate the database (10 sec)

```bash
make migrate
```

## 9. Run tests (1 min)

```bash
make test
```

You should see `55 passed`. If not, jump to [docs/FAQ.md](FAQ.md).

## 10. Boot the agent (5 sec)

```bash
make run
```

You'll see:

```
INFO apply-agent | apply-agent starting (dry_run=True)
INFO src.telegram_bot.bot | telegram bot polling
```

## 11. Your first dry-run application (60-90 sec)

From Telegram, send your bot:

```
/apply https://boards.greenhouse.io/<some-company>/jobs/<id>
```

(Use any Greenhouse job posting URL.)

Within 30 seconds:

- A Chromium window opens.
- The agent navigates to the JD, parses the role.
- Pre-flight checks pass (window, daily cap, cooldown).
- Resume selector picks the closest variant.
- Tailor calls Gemini twice (worst case) and validates the output.
- Renderer produces a PDF in `data/tailored/`.

Within 60 seconds, you get an approval card in Telegram:

```
Approval needed — app #1

Company: ExampleCo
Role: Staff Engineer
ATS: greenhouse  Tier: 1
Resume: <uuid>__master__ExampleCo__Staff_Engineer.pdf
Variant: master
UUID: a4f2...
Validator: OK

[✅ Submit] [✗ Reject] [📷 Screenshot] [✏️ Edit]
```

Hit **Submit**. Because `dry_run=True` (the safe default), the agent will fill the form **but not click the final Submit button**. You'll see a screenshot of the filled form in `data/screenshots/`.

## 12. Inspect the output (5 min)

```bash
ls -la data/tailored/   # PDFs the agent generated
ls -la data/screenshots/ # what the form looks like before submit
```

Open the PDF. Read every bullet. **If anything's wrong, your resume validator caught it as a False Negative — please open an issue with a small repro.**

## 13. Switch to real submissions (when you're ready)

```bash
# stop the agent (Ctrl-C)
python -m src.main --no-dry-run
```

Or from Telegram, you can run individual dry-runs / live runs by re-running the agent with the flag.

That's it. You're applying.

---

## Recommended next steps

- Read [docs/SPEC.md](SPEC.md) — understand what the system promises.
- Read [docs/ARCHITECTURE.md](ARCHITECTURE.md) — understand how it works.
- Set up the email inbox monitor (see [docs/RUNBOOK.md §8](RUNBOOK.md)) so you get Telegram alerts on interview invites.
- Set up the nightly backup (`scripts/backup.sh`) so you don't lose your vault.
- Star the repo if it works for you — it helps others find it.
