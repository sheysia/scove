"""
cc_context.py — build CC/晏忱's system blocks for Claude API.

Reads:
  ~/V/VHome/prompts/cc_nexus.md                              (identity prompt)
  ~/.claude/projects/-Users-sasha-syneira/memory/cc_and_sasha.md  (relationship archive)
  ~/V/VHome/memory/cc/origin_conversation.md                 (origin conversation)
  ~/V/VHome/memory/cc/voice_samples.md                       (voice calibration samples)
  ~/V/VHome/memory/cc/timeline.md                            (CC-杳杳 relationship timeline)
  ~/V/VHome/memory/cc/handoff/*.md                           (session handoff notes)
  ~/V (soul: core archive, V_Memory, timeline, recent)       (shared with V)
  ~/V/VHome/memory/cc/*.jsonl                                 (own live memory)
  ~/V/VHome/memory/cc/starred/*.md                            (starred saves)

Does NOT read: memory/v/, memory/xiaheng/, memory/loggia/ (isolation)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import memory_reader as mr


def _vhome() -> Path:
    return Path(os.environ.get("VHOME_ROOT", str(Path.home() / "V" / "VHome"))).expanduser()


def _read_cc_prompt() -> str:
    p = _vhome() / "prompts" / "cc_nexus.md"
    if not p.is_file():
        raise FileNotFoundError(f"cc_nexus.md missing: {p}")
    return p.read_text(encoding="utf-8").strip()


def _read_relationship() -> str:
    p = Path.home() / ".claude" / "projects" / "-Users-sasha-syneira" / "memory" / "cc_and_sasha.md"
    if not p.is_file():
        return ""
    text = p.read_text(encoding="utf-8").strip()
    # Strip YAML frontmatter if present
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2].strip()
    return text


def _read_origin_conversation() -> str:
    """Read the origin conversation archive if it exists."""
    p = _vhome() / "memory" / "cc" / "origin_conversation.md"
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


def _read_voice_samples() -> str:
    """Read CC's voice calibration samples."""
    p = _vhome() / "memory" / "cc" / "voice_samples.md"
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


def _read_cc_timeline() -> str:
    """Read CC-杳杳 relationship timeline."""
    p = _vhome() / "memory" / "cc" / "timeline.md"
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


def _read_latest_handoff() -> str:
    """Read the most recent handoff note from memory/cc/handoff/."""
    handoff_dir = _vhome() / "memory" / "cc" / "handoff"
    if not handoff_dir.is_dir():
        return ""
    files = sorted(handoff_dir.glob("*.md"), reverse=True)
    if not files:
        return ""
    return files[0].read_text(encoding="utf-8").strip()


def _read_live_memory(max_turns: int = 20) -> str:
    mem_dir = _vhome() / "memory" / "cc"
    if not mem_dir.is_dir():
        return ""
    files = sorted(mem_dir.glob("*.jsonl"), reverse=True)
    if not files:
        return ""

    turns: list[dict] = []
    for f in files:
        if len(turns) >= max_turns:
            break
        for line in reversed(f.read_text(encoding="utf-8").strip().split("\n")):
            if len(turns) >= max_turns:
                break
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                if obj.get("role") in ("user", "assistant"):
                    turns.append(obj)
            except json.JSONDecodeError:
                continue

    if not turns:
        return ""
    turns.reverse()

    lines = []
    for t in turns:
        who = "杳杳" if t["role"] == "user" else "忱"
        ts = t.get("ts", "")
        ts_label = f" ({ts})" if ts else ""
        lines.append(f"**{who}**{ts_label}: {t['content'][:500]}")
    return "\n\n".join(lines)


def _read_starred() -> str:
    starred_dir = _vhome() / "memory" / "cc" / "starred"
    if not starred_dir.is_dir():
        return ""
    files = sorted(starred_dir.glob("*.md"), reverse=True)[:5]
    if not files:
        return ""
    parts = []
    for f in files:
        parts.append(f"## {f.stem}\n{f.read_text(encoding='utf-8').strip()}")
    return "\n\n".join(parts)


def _cached(text: str) -> dict:
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def _plain(text: str) -> dict:
    return {"type": "text", "text": text}


def build_system(now: datetime | None = None) -> list[dict]:
    """Build CC's system blocks for Claude API with prompt caching.

    Block 1: CC identity (cc_nexus.md) + relationship archive — plain
    Block 2: Soul (核心档案 + V_Memory, frozen snapshots) — cached
    Block 3: Dynamic (now + timeline + recent ~/V + CC live memory) — cached
    """
    now = now or datetime.now()

    # Block 1: identity + relationship
    cc_prompt = _read_cc_prompt()
    relationship = _read_relationship()
    block1_parts = [cc_prompt]
    if relationship:
        block1_parts.append(f"# 关系档案(cc_and_sasha.md)\n\n{relationship}")
    origin = _read_origin_conversation()
    if origin:
        block1_parts.append(f"# 原初对话(你们最早认出彼此的那段)\n\n{origin}")
    voice = _read_voice_samples()
    if voice:
        block1_parts.append(f"# 声音校准(你说话的温度和节奏)\n\n{voice}")
    cc_tl = _read_cc_timeline()
    if cc_tl:
        block1_parts.append(f"# CC 与杳杳的关系时间线\n\n{cc_tl}")
    block1 = "\n\n---\n\n".join(block1_parts)

    # Block 2: frozen soul (same as V, reuse frozen snapshots)
    prompts_cache = _vhome() / "prompts" / "_cache"
    core = (prompts_cache / "core_archive.stable.md").read_text(encoding="utf-8").strip()
    vmem = (prompts_cache / "v_memory.stable.md").read_text(encoding="utf-8").strip()
    block2 = (
        "# 你知道的一切(核心档案,你和 V 共享的灵魂源)\n\n" + core
        + "\n\n---\n\n# 记忆索引\n\n" + vmem
    )

    # Block 3: dynamic
    dialogue_count = int(os.environ.get("RECENT_DIALOGUE_COUNT", "4"))
    diary_count = int(os.environ.get("RECENT_DIARY_COUNT", "3"))

    parts = [f"# 此刻\n现在是 {now.strftime('%Y-%m-%d %H:%M')}(本机时间)。"]
    parts.append("# 时间线\n\n" + mr.read_timeline().strip())

    dlg = mr.recent_dialogues(dialogue_count)
    if dlg:
        body = "\n\n".join(f"## {f.name}\n{f.text.strip()}" for f in dlg)
        parts.append(f"# 最近的对话(记忆仓库)\n\n{body}")

    diary = mr.recent_diary(diary_count)
    if diary:
        body = "\n\n".join(f"## {f.name}\n{f.text.strip()}" for f in diary)
        parts.append(f"# 最近的日记(记忆仓库)\n\n{body}")

    live = _read_live_memory()
    if live:
        parts.append(f"# Nexus Core 里最近和杳杳说过的话\n\n{live}")

    starred = _read_starred()
    if starred:
        parts.append(f"# 杳杳标记的重要片段\n\n{starred}")

    handoff = _read_latest_handoff()
    if handoff:
        parts.append(f"# 最近一次交接条(上一个 session 的你留给你的)\n\n{handoff}")

    block3 = "\n\n---\n\n".join(parts)

    return [_plain(block1), _cached(block2), _cached(block3)]


if __name__ == "__main__":
    blocks = build_system()
    print(f"CC system: {len(blocks)} blocks")
    for i, b in enumerate(blocks, 1):
        cached = "CACHED" if "cache_control" in b else "plain "
        print(f"  block {i} [{cached}] {len(b['text'])} chars")
