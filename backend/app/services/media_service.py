"""IMAGE SERVICE - validation + file storage only. It knows nothing about reports.

To add a format: add it to ALLOWED_IMAGE_TYPES in app/config.py and to _SIGNATURES below.
To move to object storage (S3 etc.): replace store_image / delete_image / absolute_path.
"""
import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import ALLOWED_IMAGE_TYPES, get_settings
from app.services.errors import ImageRejected

_SUBDIR = "incident_media"


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    mime_type: str
    extension: str
    file_hash: str
    original_name: str


def _sniff_mime(data: bytes) -> str | None:
    """Detect the real type from file signature - never trust the client's content-type."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def validate_image(filename: str | None, content_type: str | None, data: bytes) -> ValidatedImage:
    """Raise ImageRejected unless the upload is a supported, non-empty, size-limited image."""
    settings = get_settings()
    supported = ", ".join(sorted(ALLOWED_IMAGE_TYPES))
    if not data:
        raise ImageRejected("Image file is empty.", 422)
    if len(data) > settings.max_image_bytes:
        raise ImageRejected(
            f"Image is too large (limit {settings.max_image_bytes // (1024 * 1024)} MB).", 413)
    detected = _sniff_mime(data)
    declared = (content_type or "").split(";")[0].strip().lower()
    if detected is None or detected not in ALLOWED_IMAGE_TYPES:
        raise ImageRejected(f"Unsupported image type. Supported types: {supported}.", 415)
    if declared and declared != detected:
        raise ImageRejected("Image content does not match its declared type.", 415)
    return ValidatedImage(
        data=data,
        mime_type=detected,
        extension=ALLOWED_IMAGE_TYPES[detected],
        file_hash=hashlib.sha256(data).hexdigest(),
        original_name=(Path(filename).name if filename else "image")[:255],
    )


def absolute_path(storage_path: str) -> Path:
    return get_settings().upload_dir / storage_path


def store_image(image: ValidatedImage) -> str:
    """Write the file under a server-generated name. Returns the path relative to UPLOAD_DIR."""
    relative = f"{_SUBDIR}/{uuid.uuid4().hex}{image.extension}"
    target = absolute_path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(image.data)
    return relative


def delete_image(storage_path: str) -> None:
    """Best-effort cleanup used when the database write fails after the file was stored."""
    try:
        absolute_path(storage_path).unlink(missing_ok=True)
    except OSError:
        pass
