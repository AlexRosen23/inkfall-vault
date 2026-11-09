"""Generation providers. Default is `extractive` (no model). Local OpenAI-compatible servers
(LM Studio, Ollama) are detected and used only when the user asks for a generative summary.

The model only ever sees the authorized source pack. It has no tools. Its output is parsed as
JSON and every sentence/citation is validated against the stored source text (see generate.py).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

import httpx

from .config import LLM_CANDIDATES, LLM_MODEL


@dataclass
class ProviderInfo:
    name: str
    base_url: str
    available: bool
    models: list[str]
    chosen_model: str | None
    detail: str = ""


class Provider:
    name = "base"

    def complete(self, system: str, user: str, max_tokens: int = 700) -> tuple[str, dict]:
        raise NotImplementedError


class OpenAICompatible(Provider):
    def __init__(self, name: str, base_url: str, model: str, timeout: float = 120.0):
        self.name, self.base_url, self.model, self.timeout = name, base_url.rstrip("/"), model, timeout

    def complete(self, system: str, user: str, max_tokens: int = 700) -> tuple[str, dict]:
        t0 = time.perf_counter()
        body = {
            "model": self.model, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        r = httpx.post(f"{self.base_url}/chat/completions", json=body, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        content = data["choices"][0]["message"].get("content") or ""
        usage = data.get("usage") or {}
        return content, {"latency_ms": (time.perf_counter() - t0) * 1000, "usage": usage, "model": self.model,
                         "provider": self.name}


EMBED_HINT = re.compile(r"embed|nomic|bge|e5-|minilm|phonon|whisper|tts", re.I)


def detect(timeout: float = 1.0) -> list[ProviderInfo]:
    out = []
    for name, url in LLM_CANDIDATES:
        try:
            r = httpx.get(f"{url.rstrip('/')}/models", timeout=timeout)
            r.raise_for_status()
            models = [m.get("id", "") for m in r.json().get("data", [])]
            chat = [m for m in models if m and not EMBED_HINT.search(m)]
            chosen = LLM_MODEL if LLM_MODEL in models else (chat[0] if chat else None)
            out.append(ProviderInfo(name, url, bool(chosen), models, chosen,
                                    "" if chosen else "no chat model loaded"))
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            out.append(ProviderInfo(name, url, False, [], None, type(exc).__name__))
    return out


def get_provider(preferred: str | None = None) -> Provider | None:
    for info in detect():
        if info.available and (preferred in (None, "", "auto") or preferred == info.name):
            return OpenAICompatible(info.name, info.base_url, info.chosen_model or "")
    return None


def parse_json_block(raw: str) -> dict:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("model output contained no JSON object")
    return json.loads(m.group(0))


def estimate_tokens(s: str) -> int:
    """Rough estimate (chars/4). Labelled as an estimate wherever it is shown."""
    return max(1, len(s) // 4)
