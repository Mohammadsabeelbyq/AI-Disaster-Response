"""The ONLY entry point other modules should use for vector search.
`embed_fn` is injectable so tests (and other teammates) can avoid downloading a model."""
import uuid
from typing import Callable, Iterable

import numpy as np

from app.config import get_settings
from app.faiss_search import embeddings
from app.faiss_search.index import ReportVectorIndex

EmbedFn = Callable[[list[str]], np.ndarray]
_index: ReportVectorIndex | None = None


def _load_or_create(dim: int) -> ReportVectorIndex:
    global _index
    if _index is None:
        directory = get_settings().faiss_index_dir
        _index = (ReportVectorIndex.load(directory)
                  if (directory / "reports.faiss").exists() else ReportVectorIndex(dim))
    return _index


def embed(text: str, embed_fn: EmbedFn = embeddings.embed_texts) -> np.ndarray:
    """Generate an embedding for one text."""
    return embed_fn([text])[0]


def add_report(report_id: uuid.UUID, text: str, embed_fn: EmbedFn = embeddings.embed_texts,
               persist: bool = True) -> None:
    """Add one report (use report.searchable_text as `text`)."""
    vec = embed(text, embed_fn)
    index = _load_or_create(len(vec))
    index.add(report_id, vec)
    if persist:
        index.save(get_settings().faiss_index_dir)


def search(query: str, k: int = 5, embed_fn: EmbedFn = embeddings.embed_texts) -> list[tuple[str, float]]:
    """Return [(report_id, similarity)] best first."""
    vec = embed(query, embed_fn)
    return _load_or_create(len(vec)).search(vec, k)


def rebuild(reports: Iterable, embed_fn: EmbedFn = embeddings.embed_texts) -> int:
    """Throw away the index and rebuild from IncidentReport rows. Returns number indexed."""
    global _index
    reports = list(reports)
    _index = None
    if not reports:
        return 0
    vectors = embed_fn([r.searchable_text for r in reports])
    index = ReportVectorIndex(vectors.shape[1])
    for report, vec in zip(reports, vectors):
        index.add(report.id, vec)
    index.save(get_settings().faiss_index_dir)
    _index = index
    return len(reports)
