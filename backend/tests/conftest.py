"""Test setup: temp database + temp upload dir. Env vars must be set BEFORE importing the app."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="dr_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["FAISS_INDEX_DIR"] = f"{_tmp}/faiss"
os.environ["MAX_IMAGE_BYTES"] = str(1024 * 1024)  # 1 MB so the oversize test stays small

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.models  # noqa: E402,F401  (registers tables)
from app.database import Base, engine  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402

# Smallest byte strings that carry a valid signature for each supported format.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with TestClient(fastapi_app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def valid_form():
    return {"disaster_type": "FLOOD", "description": "Water entered houses near the road",
            "latitude": "10.027", "longitude": "76.308", "location_name": "Edappally"}


def rec(**over):
    base = {"disaster_type": "FIRE", "description": "Fire in a building",
            "latitude": 10.0, "longitude": 76.3}
    base.update(over)
    return base
