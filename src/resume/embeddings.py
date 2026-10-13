"""Local bge-small-en-v1.5 embeddings. Cached per-process via lru_cache.

Used by:
  - selector.py to pick a base resume per JD.
  - profile/qa_log.py to semantically match new questions.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np

log = logging.getLogger(__name__)

_MODEL_NAME = "BAAI/bge-small-en-v1.5"


@lru_cache(maxsize=1)
def _model():
    # Lazy import — sentence-transformers pulls torch (heavy).
    from sentence_transformers import SentenceTransformer

    log.info("loading %s (first call, ~30s)", _MODEL_NAME)
    return SentenceTransformer(_MODEL_NAME)


def embed(text: str) -> np.ndarray:
    """Return a (dim,) float32 array. Truncates input to model max."""
    m = _model()
    vec = m.encode(text[:8192], normalize_embeddings=True)
    return np.asarray(vec, dtype=np.float32)


def embed_batch(texts: list[str]) -> np.ndarray:
    m = _model()
    arr = m.encode([t[:8192] for t in texts], normalize_embeddings=True)
    return np.asarray(arr, dtype=np.float32)
