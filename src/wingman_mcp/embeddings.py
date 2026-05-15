"""Local sentence-transformers embedding wrapper compatible with Chroma/LangChain.

Notes on platform stability
---------------------------
On Apple Silicon (macOS, ARM64) the PyTorch MPS backend has had stability
regressions in recent releases — encoding can segfault mid-batch even with
small models. To keep ingest reliable across environments we default to
CPU-only embedding. Users who want to try GPU/MPS can opt in via the
``WINGMAN_MCP_EMBED_DEVICE`` env var (e.g. ``mps`` or ``cuda``).

We also set two env vars at import time as belt-and-braces:

* ``OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`` — required on macOS to avoid
  fork-after-Cocoa-init crashes from libraries that rely on multiprocessing.
* ``TOKENIZERS_PARALLELISM=false`` — silences HuggingFace tokenizer warnings
  and avoids deadlocks when downstream code forks.
"""
import os

# Set defensive env vars before any torch / sentence-transformers import.
os.environ.setdefault("OBJC_DISABLE_INITIALIZE_FORK_SAFETY", "YES")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from typing import List

_model = None


def _resolve_device() -> str:
    """Return the device to load the embedding model onto.

    Defaults to ``cpu`` for cross-platform reliability. Override with the
    ``WINGMAN_MCP_EMBED_DEVICE`` env var (e.g. ``mps``, ``cuda``).
    """
    return os.environ.get("WINGMAN_MCP_EMBED_DEVICE", "cpu").strip() or "cpu"


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2", device=_resolve_device())
    return _model


class LocalEmbeddings:
    """LangChain-compatible embedding class using sentence-transformers."""

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        model = _get_model()
        embeddings = model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        return embeddings.tolist()

    def embed_query(self, text: str) -> List[float]:
        model = _get_model()
        embedding = model.encode(text, show_progress_bar=False, convert_to_numpy=True)
        return embedding.tolist()
