"""text -> vector. Swap the model via EMBEDDING_MODEL, or replace embed_texts() entirely."""
from functools import lru_cache

import numpy as np

from app.config import get_settings


@lru_cache
def _model():
    from sentence_transformers import SentenceTransformer  # heavy import, load lazily
    return SentenceTransformer(get_settings().embedding_model)


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return float32 array (len(texts), dim), L2-normalised so inner product == cosine similarity."""
    vectors = _model().encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return vectors.astype("float32")
