"""Thin wrapper around a FAISS index that maps vectors <-> report ids. Persisted to disk."""
import json
import uuid
from pathlib import Path

import numpy as np


class ReportVectorIndex:
    def __init__(self, dim: int):
        import faiss  # imported lazily so the rest of the app runs without faiss installed
        self._faiss = faiss
        self.dim = dim
        self.index = faiss.IndexFlatIP(dim)   # exact cosine search; fine for thousands of reports
        self.ids: list[str] = []              # ids[i] is the report id of vector i

    def add(self, report_id: uuid.UUID, vector: np.ndarray) -> None:
        self.index.add(vector.reshape(1, -1).astype("float32"))
        self.ids.append(str(report_id))

    def search(self, vector: np.ndarray, k: int) -> list[tuple[str, float]]:
        if self.index.ntotal == 0:
            return []
        scores, positions = self.index.search(vector.reshape(1, -1).astype("float32"), k)
        return [(self.ids[p], float(s)) for p, s in zip(positions[0], scores[0]) if p != -1]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self._faiss.write_index(self.index, str(directory / "reports.faiss"))
        (directory / "reports.ids.json").write_text(json.dumps(self.ids))

    @classmethod
    def load(cls, directory: Path) -> "ReportVectorIndex":
        import faiss
        index = faiss.read_index(str(directory / "reports.faiss"))
        obj = cls(index.d)
        obj.index = index
        obj.ids = json.loads((directory / "reports.ids.json").read_text())
        return obj
