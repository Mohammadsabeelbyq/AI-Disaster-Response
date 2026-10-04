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
    assert body["submitted_at"].endswith("+00:00") or body["submitted_at"].endswith("Z")
    extraction = body["extraction"]
    assert extraction["extracted_facts"]["incident_category"] == "FLOOD"
    assert extraction["effective_facts"] == extraction["extracted_facts"]
    assert "incident_category" in extraction["confidence"]
    assert extraction["evidence"]["incident_category"]
    assert extraction["image_analysis_status"] == "NOT_PROVIDED"
    assert client.get(f"/reports/{body['id']}").json()["description"] == valid_form["description"]


def test_text_extraction_leaves_unsupported_facts_unknown(client, valid_form):
    valid_form["description"] = "A flood is reported near Edappally. Please send rescue and clean water for 12 people."
    body = client.post("/reports", data=valid_form).json()
    facts = body["extraction"]["extracted_facts"]
    assert facts["urgency"] == "HIGH"
    assert facts["affected_persons"] == 12
    assert facts["requested_assistance"] == ["RESCUE", "WATER"]
    assert facts["location_mentions"]
    assert "severity_cues" not in body["extraction"]["confidence"]


def test_coordinator_correction_preserves_source_and_extraction_history(client, valid_form):
    original = client.post("/reports", data=valid_form).json()
    client.post("/auth/logout")
    assert client.post("/auth/login", json={
        "email": "coordinator@example.test", "password": "test-coordinator-password-123",
        "role": "MANAGEMENT",
    }).status_code == 200
    facts = {**original["extraction"]["extracted_facts"], "urgency": "CRITICAL"}
    response = client.patch(f"/reports/{original['id']}/extraction", json={"facts": facts})
    assert response.status_code == 200
    updated = response.json()
    assert updated["description"] == original["description"]
    assert updated["extraction"]["extracted_facts"] == original["extraction"]["extracted_facts"]
    assert updated["extraction"]["corrected_facts"]["urgency"] == "CRITICAL"
    assert updated["extraction"]["effective_facts"]["urgency"] == "CRITICAL"
    assert updated["extraction"]["reviews"][0]["corrected_facts"]["urgency"] == "CRITICAL"
    assert updated["extraction"]["reviewed_by"]
    assert updated["extraction"]["reviewed_at"].endswith("+00:00") or updated["extraction"]["reviewed_at"].endswith("Z")


def test_reporter_cannot_correct_extraction(client, valid_form):
    report_id = client.post("/reports", data=valid_form).json()["id"]
    response = client.patch(f"/reports/{report_id}/extraction", json={"facts": {}})
    assert response.status_code == 403


def test_existing_report_gets_extraction_backfilled(client, valid_form):
    from uuid import UUID
    from app.database import SessionLocal
    from app.models.report import IncidentReport
    from app.services.report_service import backfill_missing_extractions

    report_id = client.post("/reports", data=valid_form).json()["id"]
    with SessionLocal() as db:
        report = db.get(IncidentReport, UUID(report_id))
        report.extraction = None
        db.commit()
        backfill_missing_extractions(db)
    assert client.get(f"/reports/{report_id}").json()["extraction"]["effective_facts"]


def test_optional_image_analysis_returns_advisory_cue(monkeypatch):
    from types import SimpleNamespace
    from app.services import extraction_service

    monkeypatch.setattr(extraction_service, "get_settings", lambda: SimpleNamespace(
        enable_image_analysis=True, gemini_api_key="test-key", gemini_model="test-model"))
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text":
                '{"cues":[{"cue":"standing water","confidence":0.91,"evidence":"water covers the street"}]}'}]}}]}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(extraction_service.httpx, "post", fake_post)
    status, cues = extraction_service.analyze_image(b"image-bytes", "image/png")
    assert status == "COMPLETED"
    assert cues == [{"cue": "standing water", "confidence": 0.91,
                     "evidence": "water covers the street"}]
    assert captured["headers"]["x-goog-api-key"] == "test-key"


def test_failed_optional_image_analysis_does_not_reject_report(client, valid_form, monkeypatch):
    from app.services import extraction_service

    monkeypatch.setattr(extraction_service, "analyze_image", lambda *_: ("FAILED", None))
    response = client.post("/reports", data=valid_form,
                           files={"image": ("evidence.png", PNG, "image/png")})
    assert response.status_code == 201
    assert response.json()["extraction"]["image_analysis_status"] == "FAILED"


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
