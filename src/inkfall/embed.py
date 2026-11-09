"""Local sentence-transformers embeddings (CPU). Optional: dense retrieval reports itself unavailable
when the package or the cached model is missing, and BM25 keeps working."""

from __future__ import annotations

import os
import threading

import numpy as np

from .config import EMBED_MODEL_ID, RERANK_MODEL_ID

_lock = threading.Lock()
_model = None
_reranker = None
_status: dict[str, str] = {}


def _load(model_id: str, cross: bool = False, allow_download: bool = False):
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    try:
        import sentence_transformers as st
    except ImportError as exc:  # optional extra not installed
        raise RuntimeError("sentence-transformers is not installed (uv sync --extra dense)") from exc
    cls = st.CrossEncoder if cross else st.SentenceTransformer
    try:
        return cls(model_id, device="cpu", local_files_only=True)
    except Exception:  # noqa: BLE001 - library raises several types for "not cached"
        if not allow_download:
            raise RuntimeError(f"model {model_id} is not downloaded (run make setup)") from None
        return cls(model_id, device="cpu")


def get_model(allow_download: bool = False):
    global _model
    with _lock:
        if _model is None:
            _model = _load(EMBED_MODEL_ID, allow_download=allow_download)
            _status["embed"] = "ready"
        return _model


def available() -> bool:
    try:
        get_model()
        return True
    except RuntimeError as exc:
        _status["embed"] = str(exc)
        return False


def status() -> dict[str, str]:
    available()
    return {"model_id": EMBED_MODEL_ID, "license": "Apache-2.0", "status": _status.get("embed", "unknown")}


def encode(texts: list[str]) -> np.ndarray:
    m = get_model()
    vecs = m.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def get_reranker(allow_download: bool = False):
    global _reranker
    with _lock:
        if _reranker is None:
            _reranker = _load(RERANK_MODEL_ID, cross=True, allow_download=allow_download)
        return _reranker


def reranker_available() -> bool:
    try:
        get_reranker()
        return True
    except RuntimeError:
        return False
