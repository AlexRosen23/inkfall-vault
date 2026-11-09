"""Redaction for logs, audit events and error messages. Never log document text."""

from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("api-key", re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{16,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/]{12,}=*")),
    ("password", re.compile(r"(?i)\b(pass(?:word)?|pwd|secret|token|api[_-]?key)\s*[:=]\s*\S+")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("card", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("long-hex", re.compile(r"\b[0-9a-fA-F]{40,}\b")),
]


def redact(s: str, max_len: int = 240) -> str:
    out = s
    for name, pat in PATTERNS:
        out = pat.sub(f"[REDACTED:{name}]", out)
    if len(out) > max_len:
        out = out[:max_len] + "…"
    return out


def redact_obj(obj, max_len: int = 240):
    if isinstance(obj, str):
        return redact(obj, max_len)
    if isinstance(obj, dict):
        return {k: redact_obj(v, max_len) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [redact_obj(v, max_len) for v in obj]
    return obj
