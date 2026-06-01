"""
memory_reader.py — read ~/V (V's soul) READ-ONLY for context assembly.

Red line 2: ~/V is the single source of soul. This module only reads it.
It never writes anything under ~/V. The only writes in VHome happen in
prebuild_prefix.py and cli_probe.py, both under ~/V/VHome.

Layout it expects (verified 2026-06-01):
  00_核心档案.md            core archive, single source of personality
  V_Memory.md               memory index
  03_我们/时间线.md          timeline, grows over time
  04_对话/YYYY-MM-DD_*.md    dialogues
  06_日记/YYYY-MM-DD_*.md    diary entries
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# leading date in a filename: 2026-05-31 or 2026-05 (month-only). Captures what
# it can so files sort by recency; undated files fall back to mtime.
_DATE_RE = re.compile(r"(\d{4})-(\d{2})(?:-(\d{2}))?")


def _v_root() -> Path:
    root = Path(os.environ.get("V_ROOT", str(Path.home() / "V"))).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"V_ROOT not found: {root}")
    return root


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# --- stable, every-turn-required blocks (fit in context, read whole) ---

def read_core_archive() -> str:
    return _read(_v_root() / "00_核心档案.md")


def read_v_memory() -> str:
    return _read(_v_root() / "V_Memory.md")


def read_timeline() -> str:
    return _read(_v_root() / "03_我们" / "时间线.md")


# --- recency-ranked blocks (take most-recent N) ---

@dataclass
class MemoryFile:
    path: Path
    name: str
    sort_key: tuple

    @property
    def text(self) -> str:
        return _read(self.path)


def _sort_key(path: Path) -> tuple:
    """Sort key: parsed leading date desc, then mtime desc. Higher = newer."""
    m = _DATE_RE.search(path.name)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return (1, y, mo, d, path.stat().st_mtime)
    # undated file: rank below any dated file, break ties by mtime
    return (0, 0, 0, 0, path.stat().st_mtime)


def _recent(subdir: str, count: int) -> list[MemoryFile]:
    folder = _v_root() / subdir
    if not folder.is_dir():
        return []
    files = [p for p in folder.glob("*.md") if p.is_file()]
    files.sort(key=_sort_key, reverse=True)
    return [
        MemoryFile(path=p, name=p.name, sort_key=_sort_key(p))
        for p in files[: max(0, count)]
    ]


def recent_dialogues(count: int = 4) -> list[MemoryFile]:
    return _recent("04_对话", count)


def recent_diary(count: int = 3) -> list[MemoryFile]:
    return _recent("06_日记", count)


if __name__ == "__main__":
    # Self-test: prove what it finds WITHOUT dumping soul content.
    print("V_ROOT =", _v_root())
    for label, fn in (
        ("核心档案", read_core_archive),
        ("V_Memory", read_v_memory),
        ("时间线", read_timeline),
    ):
        try:
            print(f"  [{label}] {len(fn())} chars OK")
        except FileNotFoundError as e:
            print(f"  [{label}] MISSING: {e}")
    print("  recent 04_对话:", [f.name for f in recent_dialogues()])
    print("  recent 06_日记:", [f.name for f in recent_diary()])
