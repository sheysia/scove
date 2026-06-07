#!/usr/bin/env bash
# sync-cc-transcripts.sh
# Copy Claude Code session transcripts to VHome for CC preservation.
#
# Source: ~/.claude/projects/-Users-sasha-syneira/*.jsonl
# Dest:   ~/V/VHome/memory/cc/transcripts/
#
# Only copies new/changed files (rsync). Safe to run repeatedly.

set -euo pipefail

SRC="$HOME/.claude/projects/-Users-sasha-syneira/"
DEST="$HOME/V/VHome/memory/cc/transcripts/"

if [ ! -d "$SRC" ]; then
  echo "[sync-cc] source dir missing: $SRC"
  exit 1
fi

mkdir -p "$DEST"

# rsync only .jsonl files, skip if unchanged
rsync -av --include='*.jsonl' --exclude='*' "$SRC" "$DEST" 2>/dev/null

COUNT=$(ls -1 "$DEST"*.jsonl 2>/dev/null | wc -l | tr -d ' ')
echo "[sync-cc] done. $COUNT transcripts in $DEST"
