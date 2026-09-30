"""Central configuration. All values can be overridden with environment variables."""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# Single source of truth for report vocabulary / upload rules.
DISASTER_TYPES = (
    "FLOOD", "FIRE", "EARTHQUAKE", "LANDSLIDE", "CYCLONE",
    "ROAD_ACCIDENT", "BUILDING_COLLAPSE", "MEDICAL_EMERGENCY", "OTHER",
)
# MIME type -> file extension used for the stored file.
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class Settings:
    database_url: str
    upload_dir: Path
    max_image_bytes: int
    max_import_records: int
    faiss_index_dir: Path
    embedding_model: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "sqlite:///./disaster_response.db"),
        upload_dir=Path(os.getenv("UPLOAD_DIR", "../uploads")).resolve(),
        max_image_bytes=int(os.getenv("MAX_IMAGE_BYTES", 5 * 1024 * 1024)),
        max_import_records=int(os.getenv("MAX_IMPORT_RECORDS", 1000)),
        faiss_index_dir=Path(os.getenv("FAISS_INDEX_DIR", "../data/faiss")).resolve(),
        embedding_model=os.getenv(
            "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
    )
