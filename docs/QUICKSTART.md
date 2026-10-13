# Quickstart: your first dry-run application

You need Linux, macOS, or WSL2 on Windows, plus `git`, `make` and Python 3.11+. Run everything in a terminal there, not in PowerShell.

## 1. Install (5 min)

```bash
git clone https://github.com/drajb/Job-Application-Automation.git apply-agent
cd apply-agent
make setup
```

`make setup` creates `.venv`, installs dependencies (CPU-only torch), installs Playwright's Chromium, creates `.env` and `secrets/profile.yaml` from the templates, and runs `make doctor`. The doctor lists what's still missing; the steps below fill it in.

On Ubuntu/WSL you also want:

```bash
sudo apt install age libreoffice-writer-nogui
```

## 2. Gemini key (2 min)

Create a free key at https://aistudio.google.com/apikey and put it in `.env`:

```
GEMINI_API_KEY=...
```

## 3. Your resume (5 min)

```bash
mkdir -p resumes/master
$EDITOR resumes/master/Resume_v1.md
```

Plain Markdown: `# Name`, `## Section`, `### Employer — Title (2021–present)`, `- bullet`. See `resumes/master/Resume_example.md` for the shape (the example itself is never used).

**This file is the truth source.** The tailor may reword it but every employer, title, year, number and tool in the output must already be here, or the validator rejects the draft.

More variants? Add folders like `resumes/staff-engineer/` or `resumes/engineering-manager/`. The selector picks a folder from the role, then the closest file in it.

## 4. Profile + encryption key (5 min)

```bash
make keygen                       # creates secrets/master.age.key — back it up now
$EDITOR secrets/profile.yaml      # name, contact, work authorization, salary, education
make encrypt-profile              # validates, encrypts, deletes the plaintext
```

To change it later: `make edit-profile`, edit, `make encrypt-profile`.

## 5. Database

```bash
make migrate
make doctor
```

Fix anything the doctor marks ❌.

## 6. Check fit before you apply (optional, 30 sec)

```bash
python -m src.main --fit https://boards.greenhouse.io/<company>/jobs/<id>
```

You get a fit score and the JD keywords your resume does and doesn't mention. If a missing keyword is true, add it to your resume yourself. The tailor never will.

## 7. Dry run (2 min)

```bash
python -m src.main --apply https://boards.greenhouse.io/<company>/jobs/<id>
```

A browser window opens. The agent parses the posting, runs the pre-flight checks, tailors and validates your resume, renders a PDF, fills the form, and screenshots it. In dry-run it never clicks Submit.

Look at the results:

```bash
ls data/tailored/*/      # the tailored resume (docx + pdf) per run
ls data/screenshots/     # the filled form
```

Read the PDF. If anything in it isn't true, that's a validator bug. Please open an issue with a small example.

## 8. Telegram (5 min, needed for real submissions)

1. Message `@BotFather`, send `/newbot`, copy the token.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": ...}`.
4. Add to `.env`:

```
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

`make ping` should make your phone buzz. Then `make run` and send the bot `/apply <url>`.

For every application you get the filled-form screenshot, the tailored-bullet diffs, a fit score and the missing keywords, then **✅ / ✗ / 🖥 Take over**. When the agent hits a question it can't answer from your profile, it asks you. Reply to that message and it remembers the answer next time.

## 9. Find jobs automatically (optional)

```bash
cp watchlist.example.yaml watchlist.yaml
$EDITOR watchlist.yaml     # companies you like + title/location filters
make scan
```

With the daemon running, `/scan` (and a daily scan at 9am) posts new matching roles with a 🚀 Apply button.

## 10. Real submissions

After you've watched a few dry runs:

```bash
python -m src.main --no-dry-run
```

Each submission still waits for your ✅, happens only inside your submission window, and stops at your daily cap.

## Next

- [CONFIGURATION.md](CONFIGURATION.md): every setting and command.
- [RUNBOOK.md](RUNBOOK.md): running it always-on, inbox alerts, backups.
- [PRIVACY.md](PRIVACY.md): what is stored where.
