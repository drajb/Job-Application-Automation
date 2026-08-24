# Security policy

This is an automation tool that handles credentials, a personal profile, and an inbox connection. Take it seriously.

## Reporting a vulnerability

**Do NOT open a public issue.** Instead, open a private security advisory on GitHub:

https://github.com/drajb/Job-Application-Automation/security/advisories/new

Or, if you cannot use GitHub: open a regular issue titled "Security: contact request" with no detail, and you'll be contacted privately.

Please include:

- A description of the vulnerability.
- Steps to reproduce.
- The version (commit SHA).
- Suggested fix (optional).

Expected response time: within 7 days for acknowledgment, within 30 days for a fix or mitigation plan.

## Threat model

The threat model assumes:

| Attacker | Capability | We defend |
|---|---|---|
| Random internet stranger | Cannot reach the machine | n/a — single-host design, no exposed ports |
| Compromised dev box | Read filesystem | `secrets/` is `age`-encrypted; master key is the only ground truth |
| Compromised Telegram session | Send /apply spam | `chat_id` allowlist on every handler |
| ATS site phishing | Send a fake verify email | `EmailExpectation` requires sender-domain + subject regex match before fulfilling |
| Compromised Gemini API key | Read prompts (resumes + JDs) | Key is .env-scoped; no PII besides what you submit anyway |
| Wrong-target submission | User mis-types /apply URL | Telegram approval card with company + role + diffs is mandatory pre-submit |

## Out of scope

- The `apply-agent` process is **not hardened against a compromised host**. If your dev box is rooted, your secrets are gone.
- The browser session is not isolated from your host network. Use a VPN if your home IP is something you don't want associated with applications.
- The validator catches blatant fabrication but cannot detect a tailored output that paraphrases incorrectly. That's why every submit goes through human approval.
- We do not protect against the user voluntarily uploading the wrong PDF.

## Hardening checklist

If you're running this on a shared machine:

- [ ] `chmod 600 secrets/master.age.key`
- [ ] `chmod 600 .env`
- [ ] `chmod 700 secrets/`
- [ ] Set `BACKUP_DEST` to an encrypted volume, not a plain NTFS mount
- [ ] Use a dedicated email for job applications, not your main account
- [ ] Use a dedicated Telegram bot (one bot per agent instance), not a shared one
- [ ] Keep your `RESUME_SOURCE_DIR` out of any cloud-synced folder if you've put salary expectations or visa status in the resume body

## What we will never ask for

We will never ask you to share your `secrets/master.age.key`, `.env`, or decrypted `profile.yaml` in an issue, PR, or chat. Anyone asking for these is impersonating the project.
