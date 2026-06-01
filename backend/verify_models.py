"""
verify_models.py — confirm real, available model IDs against the live API.

加固二: never trust a model ID from a doc (including our own .env example).
Run this after you fill ANTHROPIC_API_KEY in config/.env. It lists what the
API actually serves and checks that CLAUDE_CHAT_MODEL / CLAUDE_FAST_MODEL resolve.
"""

from __future__ import annotations

import os
from pathlib import Path

import anthropic
from dotenv import load_dotenv


def _load_env() -> None:
    vhome = Path(os.environ.get("VHOME_ROOT", str(Path.home() / "V" / "VHome"))).expanduser()
    load_dotenv(vhome / "config" / ".env", override=True)


def main() -> None:
    _load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is empty. Fill it in config/.env first.")
        raise SystemExit(1)

    client = anthropic.Anthropic()
    print("Models the API actually serves:")
    served = []
    for m in client.models.list():
        served.append(m.id)
        print(f"  {m.id}   ({getattr(m, 'display_name', '')})")

    print()
    for var in ("CLAUDE_CHAT_MODEL", "CLAUDE_FAST_MODEL"):
        val = os.environ.get(var, "")
        if not val:
            print(f"  {var}: (unset)")
            continue
        ok = "OK" if val in served else "NOT IN LIST  <-- fix config/.env"
        print(f"  {var} = {val}   [{ok}]")


if __name__ == "__main__":
    main()
