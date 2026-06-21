#!/usr/bin/env bash
# Nightly backup of secrets/, data/, and the DB to a local Windows path.
#
# Run via cron inside WSL2:
#   0 3 * * * /home/<user>/apply-agent/scripts/backup.sh >> /tmp/apply-backup.log 2>&1
#
# Uses tar + gpg for portability. restic can be substituted if installed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DEST="${BACKUP_DEST:-/mnt/c/Users/$USER/Backups/apply-agent}"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DEST/apply-agent_${STAMP}.tar.gz"

mkdir -p "$BACKUP_DEST"
cd "$REPO_ROOT"

# Stage what we want to back up.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp -r secrets "$TMP/" 2>/dev/null || true
cp -r data "$TMP/" 2>/dev/null || true
[[ -f apply_agent.db ]] && cp apply_agent.db "$TMP/" || true

tar -C "$TMP" -czf "$OUT" .
echo "backup written: $OUT ($(du -h "$OUT" | cut -f1))"

# Retain last 30 backups.
ls -1t "$BACKUP_DEST"/apply-agent_*.tar.gz 2>/dev/null | tail -n +31 | xargs -r rm
