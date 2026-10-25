"""Spoken alerts and instructions with ElevenLabs text-to-speech (multilingual, so Spanish works too).

Env: ELEVENLABS_API_KEY, optional ELEVENLABS_VOICE_ID and ELEVENLABS_MODEL. Audio is cached by text."""
import hashlib
import json
import os
import pathlib
import urllib.request

KEY = os.environ.get("ELEVENLABS_API_KEY", "")
VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # ElevenLabs' stock "Rachel" voice
MODEL = os.environ.get("ELEVENLABS_MODEL", "eleven_multilingual_v2")
CACHE = pathlib.Path(__file__).resolve().parent.parent / "data" / "tts"


def enabled():
    return bool(KEY)


def speak(text):
    """→ mp3 bytes."""
    text = text.strip()[:1200]
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha256(f"{VOICE}|{MODEL}|{text}".encode()).hexdigest()[:24] + ".mp3")
    if f.exists():
        return f.read_bytes()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_64",
        data=json.dumps({"text": text, "model_id": MODEL}).encode(),
        headers={"xi-api-key": KEY, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    with urllib.request.urlopen(req, timeout=60) as r:
        audio = r.read()
    f.write_bytes(audio)
    return audio
