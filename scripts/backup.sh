#!/usr/bin/env bash
# Nightly backup of secrets/, data/, and the DB to a local path.
#
# Run via cron (inside WSL2 or on Linux):
#   0 3 * * * /home/<user>/apply-agent/scripts/backup.sh >> /tmp/apply-backup.log 2>&1
#
# BACKUP_DEST defaults to ~/backups/apply-agent. On WSL you can point it at a
# Windows folder, e.g. BACKUP_DEST=/mnt/c/Users/<you>/Backups/apply-agent.
#
# The archive contains your master key and the password CSV in plain form —
# keep BACKUP_DEST somewhere only you can read (the archive itself is 0600).
# restic can be substituted if installed.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKUP_DEST="${BACKUP_DEST:-$HOME/backups/apply-agent}"
DB="${APPLY_AGENT_DB:-$REPO_ROOT/apply_agent.db}"
case "$DB" in /*) ;; *) DB="$REPO_ROOT/$DB" ;; esac
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DEST/apply-agent_${STAMP}.tar.gz"

umask 077
mkdir -p "$BACKUP_DEST"
cd "$REPO_ROOT"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
[[ -d secrets ]] && cp -r secrets "$TMP/"
[[ -d data ]] && cp -r data "$TMP/"
# Consistent snapshot even while the agent is writing (plain cp can tear a WAL DB).
if [[ -f "$DB" ]]; then
  PY="$REPO_ROOT/.venv/bin/python"
  [[ -x "$PY" ]] || PY="python3"
  "$PY" - "$DB" "$TMP/apply_agent.db" <<'EOF'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
src.close(); dst.close()
EOF
fi

tar -C "$TMP" -czf "$OUT" .
chmod 600 "$OUT"
echo "backup written: $OUT ($(du -h "$OUT" | cut -f1))"

# Retain the last 30 backups.
ls -1t "$BACKUP_DEST"/apply-agent_*.tar.gz 2>/dev/null | tail -n +31 | xargs -r rm --
