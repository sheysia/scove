"""
app.py — SCove Phase 2 backend.

Endpoints:
  GET  /                    frontend shell
  POST /api/auth/pin        PIN check (cookie 24h)
  GET  /api/sessions        list sessions
  POST /api/sessions        create session
  GET  /api/sessions/{id}   get session messages
  DELETE /api/sessions/{id} delete session
  POST /api/chat/stream     SSE streaming chat (with ?session_id=)
  GET  /sw.js               service worker (must be at root scope)

Reads ~/V only. Writes ~/V/VHome/logs/newhome/sessions/*.jsonl.
No SQLite, no Telegram, no Gemini.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import uuid
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, Cookie
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_builder as cb

# ── bootstrap ────────────────────────────────────────────────────

_VHOME = Path(os.environ.get("VHOME_ROOT", str(Path.home() / "V" / "VHome"))).expanduser()
load_dotenv(_VHOME / "config" / ".env", override=True)

_MODEL = os.environ.get("CLAUDE_CHAT_MODEL", "").strip()
_MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "2048"))
_VOICE = os.environ.get("VOICE_VARIANT", "hot").strip() or "hot"
_PIN = os.environ.get("SCOVE_PIN", "").strip()

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError("ANTHROPIC_API_KEY empty. Fill config/.env first.")
if not _MODEL:
    raise RuntimeError("CLAUDE_CHAT_MODEL unset. Run verify_models.py first.")

_client = anthropic.Anthropic()
_SESSION_NOW = datetime.now()
_SYSTEM = cb.build_system(voice_variant=_VOICE, now=_SESSION_NOW)

# PIN token: hash so we don't store raw PIN in memory after boot
_PIN_HASH = hashlib.sha256(_PIN.encode()).hexdigest() if _PIN else ""

# ── session store (jsonl-backed, in-memory index) ────────────────

_SESSIONS_DIR = _VHOME / "logs" / "newhome" / "sessions"
_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

# {session_id: {"id", "title", "created", "messages": [...]}}
_sessions: dict[str, dict] = {}


def _session_path(sid: str) -> Path:
    return _SESSIONS_DIR / f"{sid}.jsonl"


def _save_session_meta(s: dict) -> None:
    """Write/overwrite the first line (meta) of the session jsonl."""
    p = _session_path(s["id"])
    lines = []
    if p.exists():
        lines = p.read_text(encoding="utf-8").strip().split("\n")
    meta = json.dumps({
        "type": "meta", "id": s["id"], "title": s["title"], "created": s["created"]
    }, ensure_ascii=False)
    if lines and lines[0].startswith('{"type": "meta"'):
        lines[0] = meta
    else:
        lines.insert(0, meta)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_msg(sid: str, record: dict) -> None:
    p = _session_path(sid)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_sessions_from_disk() -> None:
    """On startup, rebuild index from jsonl files."""
    for p in sorted(_SESSIONS_DIR.glob("*.jsonl")):
        sid = p.stem
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        meta = {"id": sid, "title": "对话", "created": "", "messages": []}
        for line in lines:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "meta":
                meta["title"] = obj.get("title", "对话")
                meta["created"] = obj.get("created", "")
            elif obj.get("role") in ("user", "assistant"):
                meta["messages"].append({"role": obj["role"], "content": obj["content"]})
        _sessions[sid] = meta


_load_sessions_from_disk()

# ── helpers ──────────────────────────────────────────────────────

def _check_pin(request: Request) -> bool:
    if not _PIN:
        return True  # no PIN set, skip
    token = request.cookies.get("scove_pin", "")
    return token == _PIN_HASH


def _auto_title(first_msg: str) -> str:
    """Generate a short title from the first user message."""
    t = first_msg.strip().replace("\n", " ")
    return t[:30] + ("..." if len(t) > 30 else "")


# ── FastAPI ──────────────────────────────────────────────────────

app = FastAPI(title="SCove", docs_url=None, redoc_url=None)

_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")


# Service worker must be served at root scope for PWA
@app.get("/sw.js")
async def service_worker():
    return FileResponse(
        _FRONTEND / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    return (_FRONTEND / "index.html").read_text(encoding="utf-8")


# ── PIN auth ─────────────────────────────────────────────────────

@app.get("/api/auth/status")
async def auth_status(request: Request):
    return {"pin_required": bool(_PIN), "authenticated": _check_pin(request)}


@app.post("/api/auth/pin")
async def auth_pin(request: Request):
    body = await request.json()
    pin = body.get("pin", "")
    if not _PIN or pin == _PIN:
        resp = JSONResponse({"ok": True})
        if _PIN:
            resp.set_cookie(
                "scove_pin", _PIN_HASH,
                max_age=86400, httponly=True, samesite="strict",
            )
        return resp
    return JSONResponse({"ok": False, "error": "PIN incorrect"}, status_code=403)


# ── sessions ─────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions(request: Request):
    if not _check_pin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    items = []
    for s in _sessions.values():
        items.append({
            "id": s["id"], "title": s["title"], "created": s["created"],
            "message_count": len(s["messages"]),
        })
    items.sort(key=lambda x: x["created"], reverse=True)
    return items


@app.post("/api/sessions")
async def create_session(request: Request):
    if not _check_pin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    sid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    s = {
        "id": sid, "title": "新对话",
        "created": datetime.now().isoformat(timespec="seconds"),
        "messages": [],
    }
    _sessions[sid] = s
    _save_session_meta(s)
    return {"id": sid, "title": s["title"], "created": s["created"]}


@app.get("/api/sessions/{sid}")
async def get_session(sid: str, request: Request):
    if not _check_pin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    s = _sessions.get(sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "id": s["id"], "title": s["title"], "created": s["created"],
        "messages": [{"role": m["role"], "content": m["content"]} for m in s["messages"]],
    }


@app.delete("/api/sessions/{sid}")
async def delete_session(sid: str, request: Request):
    if not _check_pin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if sid in _sessions:
        del _sessions[sid]
        p = _session_path(sid)
        if p.exists():
            p.unlink()
    return {"ok": True}


# ── chat stream ──────────────────────────────────────────────────

@app.post("/api/chat/stream")
async def chat_stream(request: Request):
    if not _check_pin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    user_text = body.get("message", "").strip()
    sid = body.get("session_id", "").strip()

    if not user_text:
        return JSONResponse({"error": "empty message"}, status_code=400)

    # Auto-create session if none given
    if not sid or sid not in _sessions:
        sid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        s = {
            "id": sid, "title": _auto_title(user_text),
            "created": datetime.now().isoformat(timespec="seconds"),
            "messages": [],
        }
        _sessions[sid] = s
        _save_session_meta(s)

    session = _sessions[sid]

    # Auto-title on first message
    if not session["messages"] and session["title"] == "新对话":
        session["title"] = _auto_title(user_text)
        _save_session_meta(session)

    session["messages"].append({"role": "user", "content": user_text})
    _append_msg(sid, {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "role": "user", "content": user_text, "voice": _VOICE,
    })

    messages_for_api = [{"role": m["role"], "content": m["content"]} for m in session["messages"]]

    async def generate():
        reply_parts: list[str] = []
        try:
            with _client.messages.stream(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=_SYSTEM,
                messages=messages_for_api,
            ) as stream:
                for text in stream.text_stream:
                    reply_parts.append(text)
                    yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
                final = stream.get_final_message()
        except anthropic.APIStatusError as e:
            yield f"data: {json.dumps({'error': f'API {e.status_code}'})}\n\n"
            session["messages"].pop()
            return
        except anthropic.APIConnectionError:
            yield f"data: {json.dumps({'error': 'connection error'})}\n\n"
            session["messages"].pop()
            return

        reply = "".join(reply_parts)
        session["messages"].append({"role": "assistant", "content": reply})

        u = final.usage
        usage = {
            "input": u.input_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", None),
            "cache_write": getattr(u, "cache_creation_input_tokens", None),
            "output": u.output_tokens,
        }
        _append_msg(sid, {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "role": "assistant", "content": reply, "voice": _VOICE,
            "model": _MODEL, "usage": usage,
        })
        yield f"data: {json.dumps({'done': True, 'session_id': sid, 'title': session['title'], 'usage': usage}, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
