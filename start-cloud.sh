#!/usr/bin/env bash
set -euo pipefail

echo "[start-cloud] Initializing SCove on Fly.io..."

# Create persistent dirs on volume
mkdir -p /data/memory/{v,cc,xiaheng,loggia,council}/starred \
         /data/memory/cc/{handoff,transcripts} \
         /data/logs/newhome/sessions /data/backups

# Safe symlink: fail if a real directory exists (would mean image packaged data)
for dir in memory logs; do
  if [ -e "/app/$dir" ] && [ ! -L "/app/$dir" ]; then
    echo "ERROR: /app/$dir exists and is not a symlink" >&2
    exit 1
  fi
  ln -sfn "/data/$dir" "/app/$dir"
done

echo "[start-cloud] Symlinks: memory -> /data/memory, logs -> /data/logs"

# VERSION marker
echo "$(date -u +%FT%TZ) deploy" >> /data/VERSION

# Prebuild cache from soul_static (fail-safe, not blocking)
cd /app && python backend/prebuild_prefix.py || echo "WARN: prebuild_prefix failed, continuing"

echo "[start-cloud] Starting uvicorn..."
exec python -m uvicorn backend.app:app --host 0.0.0.0 --port 8787 --no-access-log
