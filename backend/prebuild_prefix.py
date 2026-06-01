"""
prebuild_prefix.py — freeze byte-stable snapshots of the stable memory blocks.

加固三: the prompt-cache prefix must be byte-for-byte identical every turn to
hit the cache. If we read the live ~/V files each turn, an edit mid-day busts
the cache. So we snapshot 核心档案 + V_Memory into prompts/_cache/ ONCE, and the
context builder reads those frozen copies. Re-run this when memory meaningfully
changes (after the daily archive, say) to refresh the snapshot.

Reads ~/V (read-only). Writes ONLY under ~/V/VHome/prompts/_cache/.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import memory_reader as mr


def _cache_dir() -> Path:
    vhome = Path(os.environ.get("VHOME_ROOT", str(Path.home() / "V" / "VHome"))).expanduser()
    d = vhome / "prompts" / "_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _freeze(name: str, text: str) -> str:
    out = _cache_dir() / name
    out.write_text(text, encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    print(f"  froze {name}: {len(text)} chars, sha256={digest}")
    return digest


def main() -> None:
    print("prebuild_prefix: snapshotting stable memory blocks (read-only on ~/V)")
    _freeze("core_archive.stable.md", mr.read_core_archive())
    _freeze("v_memory.stable.md", mr.read_v_memory())
    print("done. context_builder will read these frozen copies for the cache prefix.")


if __name__ == "__main__":
    main()
