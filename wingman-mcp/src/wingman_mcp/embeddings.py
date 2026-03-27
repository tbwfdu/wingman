"""Local sentence-transformers embedding wrapper compatible with Chroma/LangChain."""
from typing import List

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
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
