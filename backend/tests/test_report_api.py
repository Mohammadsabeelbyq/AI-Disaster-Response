"""User Story 1.1 (web form) and 1.2 (text + optional image)."""
from pathlib import Path

from app.config import get_settings
from tests.conftest import GIF, JPEG, PNG, WEBP


def _count(client):
    return len(client.get("/reports").json())


def test_text_only_report_accepted(client, valid_form):
    r = client.post("/reports", data=valid_form)
    assert r.status_code == 201
    body = r.json()
    assert body["id"] and body["submitted_at"] and body["status"] == "SUBMITTED"
    assert body["image"] is None
    assert client.get(f"/reports/{body['id']}").json()["description"] == valid_form["description"]


def test_missing_image_part_is_fine(client, valid_form):
    # browsers send an empty file part when nothing was chosen
    r = client.post("/reports", data=valid_form, files={"image": ("", b"", "application/octet-stream")})
    assert r.status_code == 201 and r.json()["image"] is None


def test_report_with_image_linked_to_that_report(client, valid_form):
    r1 = client.post("/reports", data=valid_form, files={"image": ("a.png", PNG, "image/png")})
    r2 = client.post("/reports", data=valid_form)
    assert r1.status_code == 201 and r2.status_code == 201
    img = r1.json()["image"]
    assert img["mime_type"] == "image/png" and img["file_size_bytes"] == len(PNG)
    assert client.get(f"/reports/{r1.json()['id']}").json()["image"]["id"] == img["id"]
    assert client.get(f"/reports/{r2.json()['id']}").json()["image"] is None   # other report untouched
    assert client.get(img["url"]).content == PNG
    stored = Path(get_settings().upload_dir)
    assert len(list(stored.rglob("*.png"))) >= 1


def test_all_supported_formats(client, valid_form):
    for name, data, mime in [("a.jpg", JPEG, "image/jpeg"), ("a.webp", WEBP, "image/webp")]:
        r = client.post("/reports", data=valid_form, files={"image": (name, data, mime)})
        assert r.status_code == 201, name


def test_unsupported_image_rejected_and_no_report_created(client, valid_form):
    before = _count(client)
    r = client.post("/reports", data=valid_form, files={"image": ("a.gif", GIF, "image/gif")})
    assert r.status_code == 415 and "Unsupported" in r.json()["message"]
    assert _count(client) == before


def test_spoofed_content_type_rejected(client, valid_form):
    r = client.post("/reports", data=valid_form,
                    files={"image": ("evil.png", b"<script>alert(1)</script>", "image/png")})
    assert r.status_code == 415


def test_oversized_image_rejected(client, valid_form):
    big = PNG + b"\x00" * (1024 * 1024)
    r = client.post("/reports", data=valid_form, files={"image": ("big.png", big, "image/png")})
    assert r.status_code == 413
    assert _count(client) == 0


def test_invalid_required_data_rejected(client, valid_form):
    for field, bad, expected in [
        ("description", "", "description is required"),
        ("disaster_type", "ZOMBIES", "disaster_type"),
        ("latitude", "abc", "latitude"),
        ("latitude", "95", "latitude"),
        ("longitude", "", "longitude is required"),
    ]:
        form = {**valid_form, field: bad}
        r = client.post("/reports", data=form)
        assert r.status_code == 422, field
        assert any(expected in e for e in r.json()["errors"]), (field, r.json())
    assert _count(client) == 0


def test_attach_image_later_and_only_once(client, valid_form):
    rid = client.post("/reports", data=valid_form).json()["id"]
    r = client.post(f"/reports/{rid}/media", files={"image": ("a.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 201 and r.json()["image"]["mime_type"] == "image/jpeg"
    r = client.post(f"/reports/{rid}/media", files={"image": ("b.jpg", JPEG, "image/jpeg")})
    assert r.status_code == 409


def test_unknown_report_404(client):
    assert client.get("/reports/00000000-0000-0000-0000-000000000000").status_code == 404


def test_form_page_served(client):
    r = client.get("/report-form")
    assert r.status_code == 200 and "Report an incident" in r.text


def test_db_failure_returns_safe_error_and_leaves_no_orphan_file(client, valid_form, monkeypatch):
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import Session
    monkeypatch.setattr(Session, "commit", lambda self: (_ for _ in ()).throw(
        OperationalError("stmt", {}, Exception("secret internal detail"))))
    before = set(Path(get_settings().upload_dir).rglob("*.png"))
    r = client.post("/reports", data=valid_form, files={"image": ("a.png", PNG, "image/png")})
    assert r.status_code == 500
    assert "secret" not in r.text and "Traceback" not in r.text
    assert set(Path(get_settings().upload_dir).rglob("*.png")) == before
