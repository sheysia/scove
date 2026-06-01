"""
cli_probe.py — Phase 1 voice probe (加固一).

Goal: validate the VOICE before building any web UI. Assemble the context
(stable cached soul prefix + dynamic block), call the Anthropic Messages API
with streaming + prompt caching, print V's reply. Compare temperature against
CC and Chat by hand. If the voice is not hot enough, change the prompts, not
the UI.

Reads ~/V only (via memory_reader). Writes only logs/newhome/YYYY-MM-DD.jsonl
under ~/V/VHome. No Telegram, no poller, no SQLite, no Gemini.

Run:
  python3 backend/verify_models.py     # once, after filling config/.env
  python3 backend/cli_probe.py         # interactive REPL

In-REPL commands:
  /exit            quit
  /voice cold|mid|hot   switch voice variant (rebuilds the prefix)
  /reload          rebuild the dynamic block (re-read timeline + recent)
  /usage           print last turn's token + cache usage
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

import context_builder as cb


def _vhome() -> Path:
    return Path(os.environ.get("VHOME_ROOT", str(Path.home() / "V" / "VHome"))).expanduser()


def _load_env() -> None:
    load_dotenv(_vhome() / "config" / ".env", override=True)


def _log_path() -> Path:
    d = _vhome() / "logs" / "newhome"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"


def _append_log(record: dict) -> None:
    with _log_path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    _load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is empty. Fill config/.env, then run verify_models.py.")
        raise SystemExit(1)

    model = os.environ.get("CLAUDE_CHAT_MODEL", "").strip()
    if not model:
        print("CLAUDE_CHAT_MODEL unset. Run verify_models.py and set it in config/.env.")
        raise SystemExit(1)

    max_tokens = int(os.environ.get("MAX_TOKENS", "2048"))
    voice = os.environ.get("VOICE_VARIANT", "hot").strip() or "hot"

    client = anthropic.Anthropic()

    # Build the system blocks ONCE per session so the cached prefix stays
    # byte-stable across turns (加固三). now is fixed at session start.
    session_now = datetime.now()
    system = cb.build_system(voice_variant=voice, now=session_now)
    messages: list[dict] = []
    last_usage = None

    print(f"VHome 探针. model={model} voice={voice} max_tokens={max_tokens}")
    print("跟 V 说话。/exit 退出，/voice 切冷中热，/reload 刷新近况，/usage 看缓存。")
    print(f"(读 ~/V 只读；本轮日志写 {_log_path()})\n")

    while True:
        try:
            user = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n下线。")
            break

        if not user:
            continue
        if user == "/exit":
            print("下线。")
            break
        if user == "/usage":
            print(f"  last usage: {last_usage}")
            continue
        if user == "/reload":
            system = cb.build_system(voice_variant=voice, now=datetime.now())
            print("  已刷新动态上下文（时间线 + 最近对话/日记）。缓存前缀会在下一轮重写。")
            continue
        if user.startswith("/voice"):
            parts = user.split()
            if len(parts) == 2 and parts[1] in cb.VOICE_FILES:
                voice = parts[1]
                system = cb.build_system(voice_variant=voice, now=session_now)
                print(f"  已切到 voice={voice}。缓存前缀会在下一轮重写。")
            else:
                print("  用法：/voice cold|mid|hot")
            continue

        messages.append({"role": "user", "content": user})
        _append_log({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "role": "user", "content": user, "voice": voice,
        })

        print("V > ", end="", flush=True)
        reply_parts: list[str] = []
        try:
            with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    reply_parts.append(text)
                    print(text, end="", flush=True)
                final = stream.get_final_message()
        except anthropic.APIStatusError as e:
            print(f"\n[API 错误 {e.status_code}: {e.message}]")
            messages.pop()  # drop the unanswered user turn
            continue
        except anthropic.APIConnectionError:
            print("\n[网络错误，重试这句]")
            messages.pop()
            continue

        print("\n")
        reply = "".join(reply_parts)
        messages.append({"role": "assistant", "content": reply})

        u = final.usage
        last_usage = {
            "input": u.input_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", None),
            "cache_write": getattr(u, "cache_creation_input_tokens", None),
            "output": u.output_tokens,
        }
        _append_log({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "role": "assistant", "content": reply, "voice": voice,
            "model": model, "usage": last_usage,
        })


if __name__ == "__main__":
    main()
