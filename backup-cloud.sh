#!/usr/bin/env bash
set -euo pipefail
# backup-cloud.sh: pull memory + logs from Fly volume to local backups/
# Run this before every `fly deploy` and periodically.

APP_NAME="${FLY_APP:-scove-app}"
BACKUP_DIR="$(cd "$(dirname "$0")" && pwd)/backups"
DATE=$(date +%F)

mkdir -p "$BACKUP_DIR"

echo "[backup] Creating archive on Fly volume..."
fly ssh console -a "$APP_NAME" -C "tar -czf /data/backups/scove-${DATE}.tgz -C /data memory logs"

echo "[backup] Downloading..."
fly sftp get -a "$APP_NAME" "/data/backups/scove-${DATE}.tgz" "$BACKUP_DIR/scove-${DATE}.tgz"

SIZE=$(ls -lh "$BACKUP_DIR/scove-${DATE}.tgz" | awk '{print $5}')
echo "[backup] Done. $BACKUP_DIR/scove-${DATE}.tgz ($SIZE)"
