"""Thin Gemini API client used by HS6 mapping + narrative generation.

Loads API key from ~/.config/gemini/keys.json (chmod 600) and exposes:
- is_available()  → True if key is set
- chat(prompt, model='gemini-2.5-flash', json_schema=None) → text or parsed JSON

Free tier (as of 2026-05):
- gemini-2.5-pro:  100 req/day  (use for HS mapping batches)
- gemini-2.5-flash: 1500 req/day (use for narrative)
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

import requests

KEY_PATH = Path.home() / ".config" / "gemini" / "keys.json"
BASE = "https://generativelanguage.googleapis.com/v1beta"


@lru_cache(maxsize=1)
def _key() -> str | None:
    if KEY_PATH.exists():
        try:
            data = json.loads(KEY_PATH.read_text())
            return data.get("api_key") or data.get("GEMINI_API_KEY")
        except (json.JSONDecodeError, OSError):
            return None
    env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_AI_API_KEY")
    return env_key


def is_available() -> bool:
    return bool(_key())


import time


def chat(
    prompt: str,
    model: str = "gemini-2.5-flash",
    json_schema: dict | None = None,
    max_output_tokens: int = 4096,
    temperature: float = 0.3,
    timeout: int = 60,
    max_retries: int = 3,
) -> str | dict:
    """One-shot chat call. If json_schema given, returns parsed dict; else returns text.

    Retries on 429 with exponential backoff (15s, 30s, 60s) — common on free tier
    when sustained RPM ceiling hits transiently.
    """
    k = _key()
    if not k:
        raise RuntimeError("Gemini API key not configured. See app/gemini_client.py for setup.")
    url = f"{BASE}/models/{model}:generateContent?key={k}"
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_output_tokens,
        },
    }
    if json_schema is not None:
        body["generationConfig"]["responseMimeType"] = "application/json"
        body["generationConfig"]["responseSchema"] = json_schema

    last_err: str = ""
    for attempt in range(max_retries):
        r = requests.post(url, json=body, timeout=timeout)
        if r.status_code in (429, 503):
            # 429 = rate limit; 503 = temporary high demand. Both warrant backoff retry.
            wait = (15 if r.status_code == 429 else 5) * (2 ** attempt)
            last_err = f"{r.status_code} backoff {wait}s (attempt {attempt+1}/{max_retries})"
            if attempt < max_retries - 1:
                time.sleep(wait)
                continue
            raise RuntimeError(f"Gemini {r.status_code} after {max_retries} retries. Body: {r.text[:300]}")
        if r.status_code != 200:
            raise RuntimeError(f"Gemini API error {r.status_code}: {r.text[:500]}")
        break

    data = r.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        finish = data.get("candidates", [{}])[0].get("finishReason", "?")
        usage = data.get("usageMetadata", {})
        raise RuntimeError(
            f"Gemini response missing text (finishReason={finish}, "
            f"thoughts={usage.get('thoughtsTokenCount', 0)}, total={usage.get('totalTokenCount', 0)}). "
            f"Try larger max_output_tokens."
        )

    if json_schema is not None:
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Gemini JSON parse error: {e}\nText: {text[:500]}")
    return text
