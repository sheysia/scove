"""
emotion_scorer.py — lightweight emotional tagging via Gemini Flash.

Scores each conversation turn with:
  valence  (0.0 = negative, 0.5 = neutral, 1.0 = positive)
  arousal  (0.0 = calm/low, 0.5 = moderate, 1.0 = intense/high)
  importance (1-10 scale)

Fire-and-forget: never blocks the SSE stream. Failures return None.
"""

from __future__ import annotations

import json
import logging
import os
import threading

_log = logging.getLogger("emotion_scorer")

_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
_SCORER_MODEL = os.environ.get("EMOTION_SCORER_MODEL", "gemini-2.5-flash-lite")

_client = None

if _GEMINI_KEY:
    try:
        from google import genai
        _client = genai.Client(api_key=_GEMINI_KEY)
    except Exception as e:
        _log.warning("emotion_scorer: Gemini client init failed: %s", e)

_SCORE_PROMPT = """\
You are an emotion tagger. Given a conversation turn pair (user message + assistant reply), output ONLY a JSON object with exactly three fields:
{"valence": <float 0.0-1.0>, "arousal": <float 0.0-1.0>, "importance": <int 1-10>}

Scales:
- valence: 0.0 = very negative/painful, 0.5 = neutral, 1.0 = very positive/joyful
- arousal: 0.0 = calm/sleepy/quiet, 0.5 = moderate, 1.0 = intense/excited/urgent
- importance: 1-3 routine small talk, 4-6 meaningful, 7-8 significant emotional moment, 9-10 milestone/relationship-defining

Output raw JSON only. No markdown, no explanation."""


def _do_score(user_text: str, assistant_text: str, callback) -> None:
    """Run scoring in background thread, call callback(result_dict) when done."""
    if not _client:
        return
    try:
        from google.genai import types
        prompt = f"User: {user_text[:500]}\nAssistant: {assistant_text[:500]}"
        resp = _client.models.generate_content(
            model=_SCORER_MODEL,
            contents=[prompt],
            config=types.GenerateContentConfig(
                system_instruction=_SCORE_PROMPT,
                temperature=0.0,
                max_output_tokens=80,
            ),
        )
        text = resp.text.strip()
        # Strip markdown fences if model wraps it
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(text)
        result = {
            "valence": max(0.0, min(1.0, float(data.get("valence", 0.5)))),
            "arousal": max(0.0, min(1.0, float(data.get("arousal", 0.5)))),
            "importance": max(1, min(10, int(data.get("importance", 3)))),
        }
        callback(result)
    except Exception as e:
        _log.debug("emotion_scorer: scoring failed (non-fatal): %s", e)


def score_async(user_text: str, assistant_text: str, callback) -> None:
    """Fire-and-forget emotion scoring.

    callback(result_dict) is called from a background thread with:
      {"valence": float, "arousal": float, "importance": int}
    If scoring fails, callback is never called.
    """
    if not _client:
        return
    t = threading.Thread(
        target=_do_score,
        args=(user_text, assistant_text, callback),
        daemon=True,
    )
    t.start()


def score_sync(user_text: str, assistant_text: str) -> dict | None:
    """Blocking version for testing. Returns result dict or None on failure."""
    if not _client:
        return None
    result = [None]

    def cb(r):
        result[0] = r

    _do_score(user_text, assistant_text, cb)
    return result[0]
