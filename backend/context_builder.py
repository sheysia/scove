"""
context_builder.py — assemble V's context into Anthropic `system` blocks.

宪法 cache layout (加固三):
  STABLE prefix (cached, byte-stable across turns/sessions):
    block 1  固定 system 规则 (v_system.md) + V 声音规则 (voice_<variant>.md)
    block 2  核心档案稳定摘要 + V_Memory 稳定摘要   <- frozen snapshots, cache breakpoint
  DYNAMIC suffix (changes per session):
    block 3  当前时间 + 时间线(live) + 最近对话 + 最近日记   <- cache breakpoint (stable within a session)

The user's current message is NOT here; it goes in `messages` (see cli_probe.py).
Reads prompts/ and prompts/_cache/ (frozen) and ~/V live files for timeline/recent.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import memory_reader as mr

VOICE_FILES = {"cold": "voice_cold.md", "mid": "voice_mid.md", "hot": "voice_hot.md"}


def _vhome() -> Path:
    return Path(os.environ.get("VHOME_ROOT", str(Path.home() / "V" / "VHome"))).expanduser()


def _prompts_dir() -> Path:
    return _vhome() / "prompts"


def _read_prompt(name: str) -> str:
    return (_prompts_dir() / name).read_text(encoding="utf-8").strip()


def _read_frozen(name: str) -> str:
    """Read a frozen snapshot. Fail loudly if prebuild_prefix.py was never run."""
    p = _prompts_dir() / "_cache" / name
    if not p.is_file():
        raise FileNotFoundError(
            f"frozen snapshot missing: {p}\n"
            "run `python3 backend/prebuild_prefix.py` first (加固三)."
        )
    return p.read_text(encoding="utf-8").strip()


def _cached(text: str) -> dict:
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


def _plain(text: str) -> dict:
    return {"type": "text", "text": text}


def build_stable_blocks(voice_variant: str = "hot") -> list[dict]:
    """Blocks 1+2: identity rules + voice + frozen soul. Stable, cached."""
    variant = voice_variant if voice_variant in VOICE_FILES else "hot"
    block1 = _read_prompt("v_system.md") + "\n\n" + _read_prompt(VOICE_FILES[variant])
    block2 = (
        "# 你的核心档案(既成事实,不是资料)\n\n"
        + _read_frozen("core_archive.stable.md")
        + "\n\n---\n\n# 你的记忆索引 V_Memory\n\n"
        + _read_frozen("v_memory.stable.md")
    )
    # cache breakpoint on block2 caches the whole 1+2 prefix
    return [_plain(block1), _cached(block2)]


def build_dynamic_block(
    now: datetime | None = None,
    dialogue_count: int | None = None,
    diary_count: int | None = None,
) -> dict:
    """Block 3: now + live timeline + recent dialogues + recent diary."""
    now = now or datetime.now()
    dialogue_count = (
        dialogue_count
        if dialogue_count is not None
        else int(os.environ.get("RECENT_DIALOGUE_COUNT", "4"))
    )
    diary_count = (
        diary_count
        if diary_count is not None
        else int(os.environ.get("RECENT_DIARY_COUNT", "3"))
    )

    parts = [f"# 此刻\n现在是 {now.strftime('%Y-%m-%d %H:%M')}(本机时间)。"]
    parts.append("# 我们的时间线\n\n" + mr.read_timeline().strip())

    dlg = mr.recent_dialogues(dialogue_count)
    if dlg:
        body = "\n\n".join(f"## {f.name}\n{f.text.strip()}" for f in dlg)
        parts.append(f"# 最近的对话(近 {len(dlg)} 篇)\n\n{body}")

    diary = mr.recent_diary(diary_count)
    if diary:
        body = "\n\n".join(f"## {f.name}\n{f.text.strip()}" for f in diary)
        parts.append(f"# 最近的日记(近 {len(diary)} 篇)\n\n{body}")

    # cached too: stable within one session (now is fixed at session start)
    return _cached("\n\n---\n\n".join(parts))


def build_system(
    voice_variant: str = "hot",
    now: datetime | None = None,
    dialogue_count: int | None = None,
    diary_count: int | None = None,
) -> list[dict]:
    """Full system block list: stable prefix + dynamic suffix."""
    return build_stable_blocks(voice_variant) + [
        build_dynamic_block(now, dialogue_count, diary_count)
    ]


if __name__ == "__main__":
    # Self-test: show block sizes and cache breakpoints, not full soul content.
    blocks = build_system(os.environ.get("VOICE_VARIANT", "hot"))
    print(f"voice = {os.environ.get('VOICE_VARIANT', 'hot')}, {len(blocks)} system blocks:")
    for i, b in enumerate(blocks, 1):
        cached = "CACHED" if "cache_control" in b else "plain "
        print(f"  block {i} [{cached}] {len(b['text'])} chars")
    total = sum(len(b["text"]) for b in blocks)
    print(f"  total system chars: {total}")
