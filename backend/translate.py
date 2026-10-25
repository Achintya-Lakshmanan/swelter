"""Spanish versions of live NWS alert text with the Gemini API. NWS publishes Spanish for some products but not
reliably for Philadelphia's alerts, so the app translates the English text and labels it as machine-translated.

Env: GEMINI_API_KEY, optional GEMINI_MODEL."""
import json
import os
import urllib.request

KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
_cache = {}

PROMPT = ("Translate this U.S. National Weather Service alert text into clear, plain Spanish for Philadelphia "
          "residents. Keep times, numbers and place names exactly. Return only the translation.\n\n")


def enabled():
    return bool(KEY)


def to_spanish(text):
    if not text or not KEY:
        return None
    if text in _cache:
        return _cache[text]
    body = {"contents": [{"parts": [{"text": PROMPT + text}]}], "generationConfig": {"temperature": 0.2}}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": KEY})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.load(r)
    text_es = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"]).strip()
    _cache[text] = text_es
    return text_es
