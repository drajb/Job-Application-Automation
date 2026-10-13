# Security policy

This tool handles credentials, a personal profile and an inbox connection.

## Reporting a vulnerability

**Don't open a public issue.** Open a private advisory:

https://github.com/drajb/Job-Application-Automation/security/advisories/new

Include a description, steps to reproduce, the version or commit, and a suggested fix if you have one. Expect an acknowledgment within 7 days.

## Threat model

| Threat | Mitigation |
|---|---|
| Someone else messages your bot | Every command, button and reply is checked against `TELEGRAM_CHAT_ID`. Use a private chat, not a group. |
| A job page tries to instruct the LLM (prompt injection) | Page text is marked untrusted in prompts; submit clicks, file uploads other than your resume, and off-site navigation are blocked in code. |
| Fake verification email | Sender must be the portal's domain or a subdomain (not a lookalike), DKIM must pass when the server records it, and the link must point at that domain. |
| Fabricated resume content | Validator rejects new employers, titles, years, numbers, tools and URLs; you approve bullet diffs before submit. |
| Submitting the wrong thing | You approve a screenshot of the filled form; window and daily cap are re-checked right before Submit. |
| Leaked portal passwords | age-encrypted per row; never sent to the LLM; CSV mirror is 0600 with spreadsheet-formula escaping. |
| Leaked Gemini key | Lives only in `.env`; worst case someone reads your prompts or uses your quota. Revoke it in AI Studio. |

## Not protected

- **A compromised machine.** `secrets/master.age.key` sits next to the encrypted data, so anyone who can read your files can decrypt them. Disk encryption is your protection here.
- **The plaintext CSV mirror and backups** contain your portal passwords. Keep them off shared or cloud-synced folders.
- File permissions aren't enforced on Windows drives mounted in WSL (`/mnt/c`). Keep the repo under `~`.
- Subtle misleading rewording that uses only your own facts. That's what the approval step is for.

## Hardening checklist

- [ ] Repo on a Linux/macOS filesystem (not `/mnt/c`), disk encryption on
- [ ] `chmod 600 .env` (the agent sets 0600/0700 on `secrets/` itself)
- [ ] Master key backed up in a password manager
- [ ] `BACKUP_DEST` private and not synced unencrypted
- [ ] A dedicated mailbox and a dedicated bot for this agent

## What we'll never ask for

Your `secrets/master.age.key`, `.env`, profile or password CSV. Anyone asking for them in an issue or chat is not from this project.
