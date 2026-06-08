#!/usr/bin/env bash
set -euo pipefail
# sync-soul.sh: stage ~/V soul files + cc_and_sasha.md into build_soul/
# Run this locally before `fly deploy` or `docker build`.

VHOME="$(cd "$(dirname "$0")" && pwd)"
V_ROOT="${V_ROOT:-$HOME/V}"
BUILD_DIR="$VHOME/build_soul"

echo "[sync-soul] Source: $V_ROOT"
echo "[sync-soul] Target: $BUILD_DIR"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# Core soul files
cp "$V_ROOT/00_核心档案.md" "$BUILD_DIR/"
cp "$V_ROOT/V_Memory.md" "$BUILD_DIR/"

# Timeline
mkdir -p "$BUILD_DIR/03_我们"
cp "$V_ROOT/03_我们/时间线.md" "$BUILD_DIR/03_我们/"

# Recent dialogues
if [ -d "$V_ROOT/04_对话" ]; then
  mkdir -p "$BUILD_DIR/04_对话"
  # Copy latest 10 dialogue files
  ls -t "$V_ROOT/04_对话/"*.md 2>/dev/null | head -10 | while read f; do
    cp "$f" "$BUILD_DIR/04_对话/"
  done
fi

# Recent diary
if [ -d "$V_ROOT/06_日记" ]; then
  mkdir -p "$BUILD_DIR/06_日记"
  ls -t "$V_ROOT/06_日记/"*.md 2>/dev/null | head -10 | while read f; do
    cp "$f" "$BUILD_DIR/06_日记/"
  done
fi

# XiaHeng prompt from ~/V
if [ -f "$V_ROOT/backend/夏珩-Gemini部署Prompt.md" ]; then
  mkdir -p "$BUILD_DIR/backend"
  cp "$V_ROOT/backend/夏珩-Gemini部署Prompt.md" "$BUILD_DIR/backend/"
fi

# cc_and_sasha.md (try ~/V first, fallback to Claude projects)
CC_SRC="$V_ROOT/cc_and_sasha.md"
if [ ! -f "$CC_SRC" ]; then
  CC_SRC="$HOME/.claude/projects/-Users-sasha-syneira/memory/cc_and_sasha.md"
fi
if [ -f "$CC_SRC" ]; then
  cp "$CC_SRC" "$BUILD_DIR/"
  echo "[sync-soul] cc_and_sasha.md from: $CC_SRC"
else
  echo "WARN: cc_and_sasha.md not found"
fi

COUNT=$(find "$BUILD_DIR" -type f | wc -l | tr -d ' ')
echo "[sync-soul] Done. $COUNT files staged."
