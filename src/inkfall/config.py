"""Runtime configuration. Everything is local; nothing here is a secret."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = Path(os.environ.get("INKFALL_CORPUS_DIR", ROOT / "corpus"))
EVAL_DIR = ROOT / "eval"
DATA_DIR = Path(os.environ.get("INKFALL_DATA_DIR", ROOT / "data"))

API_PORT = int(os.environ.get("INKFALL_API_PORT", "5110"))
WEB_PORT = int(os.environ.get("INKFALL_WEB_PORT", "5111"))

# Embedding model used for dense retrieval (Apache-2.0, ~90 MB). Recorded in docs/DATASETS_AND_LICENSES.md.
EMBED_MODEL_ID = os.environ.get("INKFALL_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
# Optional cross-encoder for the separately measured rerank experiment (opt-in download).
RERANK_MODEL_ID = os.environ.get("INKFALL_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L6-v2")

# Optional local OpenAI-compatible generation backends. Detected, never required.
LLM_CANDIDATES = [
    ("lmstudio", os.environ.get("INKFALL_LMSTUDIO_URL", "http://127.0.0.1:1234/v1")),
    ("ollama", os.environ.get("INKFALL_OLLAMA_URL", "http://127.0.0.1:11434/v1")),
]
LLM_MODEL = os.environ.get("INKFALL_LLM_MODEL", "")  # empty = first chat model the backend lists

# Limits
MAX_QUERY_CHARS = 500
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
SESSION_TTL_SECONDS = 8 * 3600
AUDIT_RETENTION_DAYS = int(os.environ.get("INKFALL_AUDIT_RETENTION_DAYS", "30"))
RATE_LIMIT_PER_MINUTE = int(os.environ.get("INKFALL_RATE_LIMIT_PER_MINUTE", "120"))


def db_path() -> Path:
    return Path(os.environ.get("INKFALL_DB", DATA_DIR / "inkfall.db"))
