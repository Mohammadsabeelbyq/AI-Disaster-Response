"""FAISS module smoke test using a fake embedder (no model download)."""
import uuid

import pytest

# Skip this whole file (instead of erroring) when the optional FAISS packages aren't installed.
np = pytest.importorskip("numpy")
pytest.importorskip("faiss")

from app.faiss_search import service  # noqa: E402


def fake_embed(texts):
    """Bag-of-letters vectors: similar strings => similar vectors."""
    out = np.zeros((len(texts), 26), dtype="float32")
    for i, t in enumerate(texts):
        for ch in t.lower():
            if "a" <= ch <= "z":
                out[i, ord(ch) - 97] += 1
        out[i] /= np.linalg.norm(out[i]) or 1
    return out


class R:
    def __init__(self, text):
        self.id, self.searchable_text = uuid.uuid4(), text


def test_rebuild_and_search():
    reports = [R("flood water rising near river"), R("building fire smoke"), R("earthquake tremor")]
    assert service.rebuild(reports, fake_embed) == 3
    hits = service.search("river flood", k=1, embed_fn=fake_embed)
    assert hits[0][0] == str(reports[0].id)


def test_add_report_then_search():
    service.rebuild([R("something unrelated")], fake_embed)
    new = R("landslide blocks mountain road")
    service.add_report(new.id, new.searchable_text, fake_embed)
    assert service.search("landslide road", k=1, embed_fn=fake_embed)[0][0] == str(new.id)
