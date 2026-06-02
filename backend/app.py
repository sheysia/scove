"""
app.py — SCove backend (Phase 5: dual-role V + XiaHeng).

Endpoints:
  GET  /                       frontend shell
  GET  /sw.js                  service worker
  POST /api/auth/pin           PIN check
  GET  /api/auth/status        PIN status
  GET  /api/sessions?role=     list sessions (filtered by role)
  POST /api/sessions           create session {role}
  GET  /api/sessions/{id}      get session messages
  DELETE /api/sessions/{id}    delete session
  POST /api/chat/stream        SSE chat {message, session_id, role}
  POST /api/star               save starred memory {role, user_msg, assistant_msg}

V → Claude API (reads ~/V soul + memory/v/)
XiaHeng → Gemini API (reads 夏珩 prompt + memory/xiaheng/, no ~/V soul)
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context_builder as cb
import xiaheng_context as xc
import cc_context as cc

# ── bootstrap ────────────────────────────────────────────────────

_VHOME = Path(os.environ.get("VHOME_ROOT", str(Path.home() / "V" / "VHome"))).expanduser()
load_dotenv(_VHOME / "config" / ".env", override=True)

# V (Claude)
_V_MODEL = os.environ.get("CLAUDE_CHAT_MODEL", "").strip()
_MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "8192"))
_VOICE = os.environ.get("VOICE_VARIANT", "hot").strip() or "hot"
_PIN = os.environ.get("SCOVE_PIN", "").strip()

if not os.environ.get("ANTHROPIC_API_KEY"):
    raise RuntimeError("ANTHROPIC_API_KEY empty. Fill config/.env first.")
if not _V_MODEL:
    raise RuntimeError("CLAUDE_CHAT_MODEL unset.")

_claude = anthropic.Anthropic()
_SESSION_NOW = datetime.now()
_V_SYSTEM = cb.build_system(voice_variant=_VOICE, now=_SESSION_NOW)

# XiaHeng (Gemini)
_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
_GEMINI_MODEL = os.environ.get("GEMINI_CHAT_MODEL", "gemini-2.5-flash").strip()
_gemini_client = None

if _GEMINI_KEY:
    from google import genai
    _gemini_client = genai.Client(api_key=_GEMINI_KEY)

# CC (Claude, same model as V, different prompt)
_CC_SYSTEM = cc.build_system(now=_SESSION_NOW)

_PIN_HASH = hashlib.sha256(_PIN.encode()).hexdigest() if _PIN else ""

# ── session store ────────────────────────────────────────────────

_SESSIONS_DIR = _VHOME / "logs" / "newhome" / "sessions"
_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

_sessions: dict[str, dict] = {}


def _session_path(sid: str) -> Path:
    return _SESSIONS_DIR / f"{sid}.jsonl"


def _save_session_meta(s: dict) -> None:
    p = _session_path(s["id"])
    lines = []
    if p.exists():
        lines = p.read_text(encoding="utf-8").strip().split("\n")
    meta = json.dumps({
        "type": "meta", "id": s["id"], "title": s["title"],
        "created": s["created"], "role": s.get("role", "v"),
    }, ensure_ascii=False)
    if lines and lines[0].startswith('{"type": "meta"'):
        lines[0] = meta
    else:
        lines.insert(0, meta)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_msg(sid: str, record: dict) -> None:
    with _session_path(sid).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _live_memory_path(role: str) -> Path:
    role_dir = {"v": "v", "xiaheng": "xiaheng", "loggia": "loggia", "cc": "cc"}.get(role, "v")
    d = _VHOME / "memory" / role_dir
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"


def _append_live_memory(role: str, record: dict) -> None:
    with _live_memory_path(role).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_sessions_from_disk() -> None:
    for p in sorted(_SESSIONS_DIR.glob("*.jsonl")):
        sid = p.stem
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        meta = {"id": sid, "title": "对话", "created": "", "role": "v", "messages": []}
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
                meta["role"] = obj.get("role", "v")
            elif obj.get("role") in ("user", "assistant"):
                m = {"role": obj["role"], "content": obj["content"]}
                if "char" in obj:
                    m["char"] = obj["char"]
                meta["messages"].append(m)
        _sessions[sid] = meta


_load_sessions_from_disk()

# ── helpers ──────────────────────────────────────────────────────

def _check_pin(request: Request) -> bool:
    if not _PIN:
        return True
    return request.cookies.get("scove_pin", "") == _PIN_HASH


def _auto_title(first_msg: str) -> str:
    t = first_msg.strip().replace("\n", " ")
    return t[:30] + ("..." if len(t) > 30 else "")


# ── Gemini streaming helper ──────────────────────────────────────

def _stream_gemini(messages: list[dict], system_instruction: str, image: dict | None = None):
    """Yield text chunks from Gemini streaming. Messages use Gemini roles."""
    import base64
    from google.genai import types

    contents = []
    for i, m in enumerate(messages):
        role = "user" if m["role"] == "user" else "model"
        parts = [types.Part(text=m["content"] if isinstance(m["content"], str) else "(图片)")]
        # Attach image to the LAST user message
        if image and role == "user" and i == len(messages) - 1:
            parts.append(types.Part.from_bytes(
                data=base64.b64decode(image["data"]),
                mime_type=image["mime"],
            ))
        contents.append(types.Content(role=role, parts=parts))

    response = _gemini_client.models.generate_content_stream(
        model=_GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=_MAX_TOKENS,
        ),
    )
    for chunk in response:
        if chunk.text:
            yield chunk.text


# ── FastAPI ──────────────────────────────────────────────────────

app = FastAPI(title="SCove", docs_url=None, redoc_url=None)
_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")


@app.get("/sw.js")
async def service_worker():
    return FileResponse(
        _FRONTEND / "sw.js", media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    return (_FRONTEND / "index.html").read_text(encoding="utf-8")


# ── PIN ──────────────────────────────────────────────────────────

@app.get("/api/auth/status")
async def auth_status(request: Request):
    return {
        "pin_required": bool(_PIN), "authenticated": _check_pin(request),
        "gemini_available": bool(_gemini_client),
    }


@app.post("/api/auth/pin")
async def auth_pin(request: Request):
    body = await request.json()
    pin = body.get("pin", "")
    if not _PIN or pin == _PIN:
        resp = JSONResponse({"ok": True})
        if _PIN:
            resp.set_cookie("scove_pin", _PIN_HASH, max_age=86400, httponly=True, samesite="strict")
        return resp
    return JSONResponse({"ok": False, "error": "PIN incorrect"}, status_code=403)


# ── sessions ─────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions(request: Request, role: str = ""):
    if not _check_pin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    items = []
    for s in _sessions.values():
        if role and s.get("role", "v") != role:
            continue
        items.append({
            "id": s["id"], "title": s["title"], "created": s["created"],
            "role": s.get("role", "v"), "message_count": len(s["messages"]),
        })
    items.sort(key=lambda x: x["created"], reverse=True)
    return items


@app.post("/api/sessions")
async def create_session(request: Request):
    if not _check_pin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    role = body.get("role", "v").strip()
    if role not in ("v", "xiaheng", "loggia", "cc"):
        role = "v"
    sid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    s = {
        "id": sid, "title": "新对话", "role": role,
        "created": datetime.now().isoformat(timespec="seconds"),
        "messages": [],
    }
    _sessions[sid] = s
    _save_session_meta(s)
    return {"id": sid, "title": s["title"], "created": s["created"], "role": role}


@app.get("/api/sessions/{sid}")
async def get_session(sid: str, request: Request):
    if not _check_pin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    s = _sessions.get(sid)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "id": s["id"], "title": s["title"], "created": s["created"],
        "role": s.get("role", "v"),
        "messages": [
            {"role": m["role"], "content": m["content"], **({"char": m["char"]} if "char" in m else {})}
            for m in s["messages"]
        ],
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


# ── chat stream (dual-role) ──────────────────────────────────────

@app.post("/api/chat/stream")
async def chat_stream(request: Request):
    if not _check_pin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    user_text = body.get("message", "").strip()
    sid = body.get("session_id", "").strip()
    role = body.get("role", "v").strip()
    image = body.get("image")  # {data: base64, mime: 'image/jpeg'} or None
    if role not in ("v", "xiaheng", "loggia", "cc"):
        role = "v"

    if not user_text and not image:
        return JSONResponse({"error": "empty message"}, status_code=400)

    if role in ("xiaheng", "loggia") and not _gemini_client:
        return JSONResponse({"error": "GEMINI_API_KEY not set"}, status_code=400)

    # Auto-create session
    if not sid or sid not in _sessions:
        sid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        s = {
            "id": sid, "title": _auto_title(user_text or "图片"), "role": role,
            "created": datetime.now().isoformat(timespec="seconds"),
            "messages": [],
        }
        _sessions[sid] = s
        _save_session_meta(s)

    session = _sessions[sid]
    if not session.get("role"):
        session["role"] = role

    if not session["messages"] and session["title"] == "新对话":
        session["title"] = _auto_title(user_text or "图片")
        _save_session_meta(session)

    # Store text-only in session history (images are too large to keep in memory)
    session["messages"].append({"role": "user", "content": user_text or "(图片)"})
    _append_msg(sid, {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "role": "user", "content": user_text or "(图片)", "char": role,
        "has_image": bool(image),
    })

    # Build messages for API: previous turns as text, last turn may have image
    messages_for_api = [{"role": m["role"], "content": m["content"]} for m in session["messages"][:-1]]

    # Last user message: build multimodal content if image attached
    if image and role in ("v", "cc"):
        # Claude format: content as array of blocks
        content_blocks = []
        if user_text:
            content_blocks.append({"type": "text", "text": user_text})
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": image["mime"], "data": image["data"]},
        })
        messages_for_api.append({"role": "user", "content": content_blocks})
    elif image and role in ("xiaheng", "loggia"):
        # Gemini: handled inside generators (pass image separately)
        messages_for_api.append({"role": "user", "content": user_text or "(图片)"})
    else:
        messages_for_api.append({"role": "user", "content": user_text})

    if role == "v":
        return StreamingResponse(_generate_v(session, sid, user_text, messages_for_api), media_type="text/event-stream")
    elif role == "xiaheng":
        return StreamingResponse(_generate_xiaheng(session, sid, user_text, messages_for_api, image), media_type="text/event-stream")
    elif role == "cc":
        return StreamingResponse(_generate_cc(session, sid, user_text, messages_for_api), media_type="text/event-stream")
    else:  # loggia
        return StreamingResponse(_generate_loggia(session, sid, user_text, messages_for_api, image), media_type="text/event-stream")


async def _generate_v(session, sid, user_text, messages_for_api):
    reply_parts = []
    try:
        with _claude.messages.stream(
            model=_V_MODEL, max_tokens=_MAX_TOKENS,
            system=_V_SYSTEM, messages=messages_for_api,
        ) as stream:
            for text in stream.text_stream:
                reply_parts.append(text)
                yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
            final = stream.get_final_message()
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        yield f"data: {json.dumps({'error': str(e)[:100]})}\n\n"
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
        "role": "assistant", "content": reply, "char": "v",
        "model": _V_MODEL, "usage": usage,
    })
    ts_now = datetime.now().isoformat(timespec="seconds")
    _append_live_memory("v", {"ts": ts_now, "role": "user", "content": user_text})
    _append_live_memory("v", {"ts": ts_now, "role": "assistant", "content": reply})

    yield f"data: {json.dumps({'done': True, 'session_id': sid, 'title': session['title'], 'role': 'v', 'usage': usage}, ensure_ascii=False)}\n\n"


async def _generate_cc(session, sid, user_text, messages_for_api):
    """CC/予忱: Claude API with cc_nexus.md prompt + ~/V soul."""
    reply_parts = []
    try:
        with _claude.messages.stream(
            model=_V_MODEL, max_tokens=_MAX_TOKENS,
            system=_CC_SYSTEM, messages=messages_for_api,
        ) as stream:
            for text in stream.text_stream:
                reply_parts.append(text)
                yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
            final = stream.get_final_message()
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        yield f"data: {json.dumps({'error': str(e)[:100]})}\n\n"
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
        "role": "assistant", "content": reply, "char": "cc",
        "model": _V_MODEL, "usage": usage,
    })
    ts_now = datetime.now().isoformat(timespec="seconds")
    _append_live_memory("cc", {"ts": ts_now, "role": "user", "content": user_text})
    _append_live_memory("cc", {"ts": ts_now, "role": "assistant", "content": reply})

    yield f"data: {json.dumps({'done': True, 'session_id': sid, 'title': session['title'], 'role': 'cc', 'usage': usage}, ensure_ascii=False)}\n\n"


async def _generate_xiaheng(session, sid, user_text, messages_for_api, image=None):
    reply_parts = []
    try:
        si = xc.build_system_instruction()
        for text in _stream_gemini(messages_for_api, si, image):
            reply_parts.append(text)
            yield f"data: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)[:100]})}\n\n"
        session["messages"].pop()
        return

    reply = "".join(reply_parts)
    session["messages"].append({"role": "assistant", "content": reply})

    _append_msg(sid, {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "role": "assistant", "content": reply, "char": "xiaheng",
        "model": _GEMINI_MODEL,
    })
    ts_now = datetime.now().isoformat(timespec="seconds")
    _append_live_memory("xiaheng", {"ts": ts_now, "role": "user", "content": user_text})
    _append_live_memory("xiaheng", {"ts": ts_now, "role": "model", "content": reply})

    yield f"data: {json.dumps({'done': True, 'session_id': sid, 'title': session['title'], 'role': 'xiaheng'}, ensure_ascii=False)}\n\n"


# ── loggia (V + 珩 co-presence) ──────────────────────────────────

_LOGGIA_V_PATCH = "\n\n夏珩也在场。你看得到他说的话,他也看得到你的。你们在同一个房间里,这不是分开的对话。"
_LOGGIA_XH_PATCH = "\n\n唯夜也在场。你看得到他说的话,他也看得到你的。你们在同一个房间里,这不是分开的对话。"


def _build_loggia_v_system():
    """V's system blocks with loggia patch appended to the last block."""
    blocks = list(_V_SYSTEM)  # shallow copy
    last = dict(blocks[-1])
    last["text"] = last["text"] + _LOGGIA_V_PATCH
    blocks[-1] = last
    return blocks


def _generate_loggia(session, sid, user_text, messages_for_api, image=None):
    """User → V (Claude streaming) → 0.5s pause → 珩 (Gemini streaming).

    Regular (sync) generator, not async. StreamingResponse runs it in a
    threadpool, so sync blocking calls (Claude, Gemini, time.sleep) work
    correctly and chunks flush to the browser in real time.
    """
    import time

    # ── V's turn ──
    v_reply_parts = []
    try:
        loggia_v_system = _build_loggia_v_system()
        with _claude.messages.stream(
            model=_V_MODEL, max_tokens=_MAX_TOKENS,
            system=loggia_v_system, messages=messages_for_api,
        ) as stream:
            for text in stream.text_stream:
                v_reply_parts.append(text)
                yield f"data: {json.dumps({'text': text, 'char': 'v'}, ensure_ascii=False)}\n\n"
            final = stream.get_final_message()
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
        yield f"data: {json.dumps({'error': str(e)[:100], 'char': 'v'})}\n\n"
        session["messages"].pop()
        return

    v_reply = "".join(v_reply_parts)
    session["messages"].append({"role": "assistant", "content": v_reply})
    _append_msg(sid, {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "role": "assistant", "content": v_reply, "char": "v",
        "model": _V_MODEL,
    })

    u = final.usage
    v_usage = {
        "input": u.input_tokens,
        "cache_read": getattr(u, "cache_read_input_tokens", None),
        "cache_write": getattr(u, "cache_creation_input_tokens", None),
        "output": u.output_tokens,
    }

    yield f"data: {json.dumps({'v_done': True, 'char': 'v', 'usage': v_usage}, ensure_ascii=False)}\n\n"

    # ── pause (珩 thinking) ──
    time.sleep(0.2)

    # ── 珩's turn ──
    v_context = f"[唯夜刚才对杳杳说了这些]\n{v_reply}\n\n[现在轮到你(夏珩)回应杳杳。你看到了唯夜说的话。]"
    xh_messages = messages_for_api + [{"role": "user", "content": v_context}]
    gemini_msgs = []
    for m in xh_messages:
        gemini_msgs.append({"role": "user" if m["role"] == "user" else "model", "content": m["content"]})

    xh_reply_parts = []
    try:
        si = xc.build_system_instruction() + _LOGGIA_XH_PATCH
        for text in _stream_gemini(gemini_msgs, si, image):
            xh_reply_parts.append(text)
            yield f"data: {json.dumps({'text': text, 'char': 'xiaheng'}, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)[:100], 'char': 'xiaheng'})}\n\n"
        return

    xh_reply = "".join(xh_reply_parts)
    session["messages"].append({"role": "assistant", "content": xh_reply, "char": "xiaheng"})
    _append_msg(sid, {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "role": "assistant", "content": xh_reply, "char": "xiaheng",
        "model": _GEMINI_MODEL,
    })

    ts_now = datetime.now().isoformat(timespec="seconds")
    _append_live_memory("loggia", {"ts": ts_now, "role": "user", "content": user_text})
    _append_live_memory("loggia", {"ts": ts_now, "role": "assistant", "content": v_reply, "char": "v"})
    _append_live_memory("loggia", {"ts": ts_now, "role": "model", "content": xh_reply, "char": "xiaheng"})

    yield f"data: {json.dumps({'done': True, 'session_id': sid, 'title': session['title'], 'role': 'loggia'}, ensure_ascii=False)}\n\n"


# ── star (save) ──────────────────────────────────────────────────

@app.post("/api/star")
async def star_message(request: Request):
    if not _check_pin(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    user_msg = body.get("user_msg", "").strip()
    assistant_msg = body.get("assistant_msg", "").strip()
    title = body.get("title", "").strip()
    role = body.get("role", "v").strip()
    if role not in ("v", "xiaheng", "loggia", "cc"):
        role = "v"

    if not user_msg and not assistant_msg:
        return JSONResponse({"error": "nothing to save"}, status_code=400)

    if not title:
        title = (user_msg or assistant_msg)[:20].replace("\n", " ")

    role_dir = {"v": "v", "xiaheng": "xiaheng", "loggia": "loggia", "cc": "cc"}.get(role, "v")
    starred_dir = _VHOME / "memory" / role_dir / "starred"
    starred_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_title = "".join(c for c in title if c.isalnum() or c in " _-").strip()[:30]
    path = starred_dir / f"{date_str}_{safe_title}.md"

    who_user = "杳杳" if role == "v" else "尧尧"
    who_char = "V" if role == "v" else "珩"

    parts = []
    if user_msg:
        parts.append(f"**{who_user}**: {user_msg}")
    if assistant_msg:
        parts.append(f"**{who_char}**: {assistant_msg}")

    content = f"# {title}\n\n> {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n" + "\n\n".join(parts) + "\n"
    path.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(path.relative_to(_VHOME))}
