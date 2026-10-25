"""User Story 1.1 (web form) and 1.2 (text + optional image)."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from pathlib import Path

from app.config import get_settings
from tests.conftest import GIF, JPEG, PNG, WEBP


def _utc_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:  # SQLite drops the timezone suffix on persistence.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _count(client):
    return len(client.get("/reports").json())


def test_text_only_report_accepted(client, valid_form):
    r = client.post("/reports", data=valid_form)
    assert r.status_code == 201
    body = r.json()
    assert body["id"] and body["submitted_at"] and body["status"] == "SUBMITTED"
    assert body["latitude"] == float(valid_form["latitude"])
    assert body["longitude"] == float(valid_form["longitude"])
    assert body["image"] is None
    assert body["submitted_at"].endswith("+00:00") or body["submitted_at"].endswith("Z")
    extraction = body["extraction"]
    assert extraction["extractor_version"] == "groq-report-analysis-unavailable-v1"
    assert extraction["extracted_facts"]["incident_category"] is None
    assert extraction["effective_facts"] == extraction["extracted_facts"]
    assert extraction["confidence"] == {}
    assert extraction["evidence"] == {}
    assert extraction["image_analysis_status"] == "NOT_PROVIDED"
    persisted = client.get(f"/reports/{body['id']}").json()
    assert persisted["id"] == body["id"]
    assert persisted["submitted_at"] == body["submitted_at"]
    assert persisted["description"] == valid_form["description"]
    assert persisted["latitude"] == float(valid_form["latitude"])
    assert persisted["longitude"] == float(valid_form["longitude"])


def test_groq_unavailable_leaves_intake_facts_unknown_for_manual_entry(client, valid_form):
    valid_form["description"] = "A flood is reported near Edappally. Please send rescue and clean water for 12 people."
    body = client.post("/reports", data=valid_form).json()
    facts = body["extraction"]["extracted_facts"]
    assert body["extraction"]["extractor_version"] == "groq-report-analysis-unavailable-v1"
    assert facts["urgency"] is None
    assert facts["affected_persons"] is None
    assert facts["requested_assistance"] == []
    assert facts["location_mentions"] == []


def test_intake_analysis_returns_empty_editable_facts_when_groq_is_unavailable(client, valid_form):
    response = client.post("/reports/analyze", json={
        "disaster_type": valid_form["disaster_type"],
        "description": "No injury was reported.",
        "location_name": "Edappally",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["analysis_status"] == "UNAVAILABLE"
    assert body["analysis_error"] == "Groq API key is not configured on the backend."
    assert body["facts"]["severity_cues"] == []
    assert body["facts"]["hazards"] == []
    assert body["priority_policy"]["weights"]


def test_intake_groq_receives_active_admin_priority_policy(client, monkeypatch):
    from app.schemas.report import ExtractedFacts
    from app.services import report_analysis_service
    from app.services.groq_planner import GroqReportAnalysis

    assert client.post("/auth/logout").status_code == 204
    admin = client.post("/auth/login", json={
        "email": "admin@example.test",
        "password": "test-admin-password-123",
        "role": "ADMIN",
    })
    assert admin.status_code == 200
    weights = {
        "life_safety_risk": 0.1,
        "urgency": 0.1,
        "affected_population": 0.1,
        "hazard_level": 0.5,
        "evidence_confidence": 0.2,
    }
    configured = client.post("/priority-configs", json={
        "weights": weights,
        "thresholds": {"CRITICAL": 75, "HIGH": 55, "MEDIUM": 30, "LOW": 0},
        "notes": "Prioritize hazard evidence.",
    })
    assert configured.status_code == 201, configured.text

    assert client.post("/auth/logout").status_code == 204
    assert client.post("/auth/login", json={
        "email": "user@example.test",
        "password": "test-user-password-123",
        "role": "USER",
    }).status_code == 200
    monkeypatch.setattr(report_analysis_service, "get_settings", lambda: SimpleNamespace(
        groq_api_key="test-key",
        groq_model="test-model",
        groq_timeout_seconds=1,
        groq_max_tokens=100,
        groq_temperature=0,
    ))
    received = {}

    def fake_groq(snapshot, **_kwargs):
        received.update(snapshot)
        return GroqReportAnalysis(
            facts=ExtractedFacts(
                incident_category="LANDSLIDE",
                severity_cues=["injured"],
                urgency="HIGH",
                hazards=["INJURY"],
                requested_assistance=["MEDICAL"],
            ),
            confidence={"severity_cues": 0.9, "hazards": 0.9},
            evidence={"severity_cues": ["injured"], "hazards": ["injured"]},
        )

    monkeypatch.setattr(report_analysis_service, "generate_report_analysis", fake_groq)
    response = client.post("/reports/analyze", json={
        "disaster_type": "LANDSLIDE",
        "description": "A person was injured near the road.",
        "location_name": "Wayanad",
    })
    assert response.status_code == 200, response.text
    assert received["admin_priority_policy"]["weights"] == weights
    assert received["admin_priority_policy"]["thresholds"]["CRITICAL"] == 75
    assert received["priority_policy_guidance"]["factor_inputs"]["hazard_level"]["hazard_mapping"]["INJURY"] == 0.75
    assert response.json()["priority_policy"]["version"] == configured.json()["version"]


def test_user_can_edit_groq_proposed_facts_before_report_is_saved(client, valid_form):
    proposed = {
        "extractor_version": "groq-report-analysis-v1",
        "facts": {
            "incident_category": "FLOOD",
            "severity_cues": ["injured"],
            "urgency": "HIGH",
            "affected_persons": None,
            "hazards": ["INJURY"],
            "requested_assistance": ["MEDICAL"],
            "location_mentions": ["Edappally"],
        },
        "confidence": {"severity_cues": 0.88},
        "evidence": {"severity_cues": ["injured"]},
        "reviewed_facts": {
            "incident_category": "FLOOD",
            "severity_cues": [],
            "urgency": "LOW",
            "affected_persons": None,
            "hazards": [],
            "requested_assistance": ["MEDICAL"],
            "location_mentions": ["Edappally"],
        },
    }
    response = client.post(
        "/reports",
        data={**valid_form, "analysis_payload": json.dumps(proposed)},
    )
    assert response.status_code == 201, response.text
    extraction = response.json()["extraction"]
    assert extraction["extracted_facts"]["severity_cues"] == ["injured"]
    assert extraction["effective_facts"]["severity_cues"] == []
    assert extraction["effective_facts"]["urgency"] == "LOW"
    assert extraction["reviews"][0]["previous_facts"] == extraction["extracted_facts"]
    assert extraction["reviews"][0]["corrected_facts"] == extraction["effective_facts"]


def test_unknown_extraction_fields_have_no_confidence_or_evidence(client, valid_form):
    valid_form["description"] = "A report was submitted."
    valid_form["location_name"] = ""
    extraction = client.post("/reports", data=valid_form).json()["extraction"]
    facts = extraction["extracted_facts"]

    assert facts["urgency"] is None
    assert facts["affected_persons"] is None
    assert facts["hazards"] == []
    assert facts["requested_assistance"] == []
    for field in ("urgency", "affected_persons", "hazards", "requested_assistance"):
        assert field not in extraction["confidence"]
        assert field not in extraction["evidence"]


def test_coordinator_correction_preserves_source_and_extraction_history(client, valid_form):
    original = client.post("/reports", data=valid_form).json()
    client.post("/auth/logout")
    assert client.post("/auth/login", json={
        "email": "coordinator@example.test", "password": "test-coordinator-password-123",
        "role": "MANAGEMENT",
    }).status_code == 200
    review_source = client.get(f"/reports/{original['id']}").json()
    assert review_source["description"] == original["description"]
    assert review_source["extraction"]["extracted_facts"] == original["extraction"]["extracted_facts"]
    assert review_source["extraction"]["evidence"] == original["extraction"]["evidence"]
    facts = {**original["extraction"]["extracted_facts"], "urgency": "CRITICAL"}
    response = client.patch(f"/reports/{original['id']}/extraction", json={"facts": facts})
    assert response.status_code == 200
    updated = response.json()
    assert updated["description"] == original["description"]
    assert updated["extraction"]["extracted_facts"] == original["extraction"]["extracted_facts"]
    assert updated["extraction"]["corrected_facts"]["urgency"] == "CRITICAL"
    assert updated["extraction"]["effective_facts"]["urgency"] == "CRITICAL"
    assert updated["extraction"]["reviews"][0]["corrected_facts"]["urgency"] == "CRITICAL"
    assert updated["extraction"]["reviews"][0]["actor_id"] == updated["extraction"]["reviewed_by"]
    assert updated["extraction"]["reviews"][0]["previous_facts"] == original["extraction"]["extracted_facts"]
    assert updated["extraction"]["reviewed_by"]
    assert updated["extraction"]["reviewed_at"].endswith("+00:00") or updated["extraction"]["reviewed_at"].endswith("Z")
    persisted = client.get(f"/reports/{original['id']}").json()
    assert persisted["description"] == original["description"]
    assert persisted["extraction"]["extracted_facts"] == original["extraction"]["extracted_facts"]
    assert persisted["extraction"]["effective_facts"]["urgency"] == "CRITICAL"
    assert len(persisted["extraction"]["reviews"]) == 1


def test_reporter_cannot_correct_extraction(client, valid_form):
    report_id = client.post("/reports", data=valid_form).json()["id"]
    response = client.patch(f"/reports/{report_id}/extraction", json={"facts": {}})
    assert response.status_code == 403


def test_reporter_cannot_correct_location(client, valid_form):
    report_id = client.post("/reports", data=valid_form).json()["id"]
    response = client.patch(f"/reports/{report_id}/location", json={
        "latitude": 12.5, "longitude": -45.25,
    })
    assert response.status_code == 403


def test_coordinator_location_correction_preserves_source_and_records_audit(client, valid_form):
    from uuid import UUID

    from app.database import SessionLocal
    from app.models.incident import WorkflowAudit

    original = client.post("/reports", data=valid_form).json()
    client.post("/auth/logout")
    assert client.post("/auth/login", json={
        "email": "coordinator@example.test", "password": "test-coordinator-password-123",
        "role": "MANAGEMENT",
    }).status_code == 200

    corrected = client.patch(f"/reports/{original['id']}/location", json={
        "latitude": 12.5, "longitude": -45.25, "location_name": "Corrected area",
    })
    assert corrected.status_code == 200
    body = corrected.json()
    assert body["latitude"] == 10.027
    assert body["longitude"] == 76.308
    assert body["location_correction"]["latitude"] == 12.5
    assert body["location_correction"]["longitude"] == -45.25
    assert body["location_correction"]["location_name"] == "Corrected area"

    invalid = client.patch(f"/reports/{original['id']}/location", json={
        "latitude": 91, "longitude": -45.25,
    })
    assert invalid.status_code == 422

    with SessionLocal() as db:
        event = db.query(WorkflowAudit).filter_by(
            report_id=UUID(original["id"]), event_type="REPORT_LOCATION_CORRECTED").one()
        assert event.details["before"]["latitude"] == 10.027
        assert event.details["after"]["latitude"] == 12.5


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


def test_bundled_image_classifier_predicts_from_image_bytes():
    from io import BytesIO
    from PIL import Image
    from app.services.extraction_service import analyze_image

    stream = BytesIO()
    Image.new("RGB", (224, 224), "white").save(stream, format="PNG")
    status, cues = analyze_image(stream.getvalue(), "image/png")

    assert status == "COMPLETED"
    assert cues[0]["cue"] in {
        "Damaged_Infrastructure", "Fire_Disaster", "Human_Damage",
        "Land_Disaster", "Non_Damage", "Water_Disaster",
    }
    assert 0 <= cues[0]["confidence"] <= 1


def test_failed_image_classification_does_not_reject_report(client, valid_form, monkeypatch):
    from app.services import extraction_service

    monkeypatch.setattr(extraction_service, "analyze_image", lambda *_: ("FAILED", None))
    response = client.post("/reports", data=valid_form,
                           files={"image": ("evidence.png", PNG, "image/png")})
    assert response.status_code == 201
    assert response.json()["extraction"]["image_analysis_status"] == "FAILED"


def test_image_prediction_is_advisory_context_not_authoritative(client, valid_form, monkeypatch):
    from app.services import extraction_service

    valid_form["disaster_type"] = "FIRE"
    cue = {"cue": "Water_Disaster", "confidence": 0.91,
           "evidence": "Predicted by the local image classifier"}
    monkeypatch.setattr(extraction_service, "analyze_image", lambda *_: ("COMPLETED", [cue]))
    response = client.post(
        "/reports", data=valid_form,
        files={"image": ("flood.png", PNG, "image/png")},
    )

    assert response.status_code == 201
    report_id = response.json()["id"]
    persisted = client.get(f"/reports/{report_id}").json()
    assert persisted["image"]["id"] == response.json()["image"]["id"]
    assert persisted["extraction"]["image_analysis_status"] == "COMPLETED"
    assert persisted["extraction"]["image_cues"] == [cue]
    assert persisted["extraction"]["extracted_facts"]["incident_category"] is None
    assert "incident_category" not in persisted["extraction"]["evidence"]
    assert "incident_category" not in persisted["extraction"]["confidence"]
    assert "image_context" in persisted["extraction"]["evidence"]
    assert "Water_Disaster" in persisted["extraction"]["evidence"]["image_context"][0]


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


def test_later_image_adds_advisory_context_without_overriding_category(client, valid_form, monkeypatch):
    from app.services import extraction_service

    report = client.post("/reports", data=valid_form).json()
    analyzed = []

    def analyze(data, mime_type):
        analyzed.append((data, mime_type))
        return "COMPLETED", [{
            "cue": "Water_Disaster",
            "confidence": 0.91,
            "evidence": "Predicted by the local image classifier",
        }]

    monkeypatch.setattr(extraction_service, "analyze_image", analyze)
    response = client.post(
        f"/reports/{report['id']}/media",
        files={"image": ("evidence.png", PNG, "image/png")},
    )

    assert response.status_code == 201
    body = response.json()
    assert analyzed == [(PNG, "image/png")]
    assert body["description"] == valid_form["description"]
    assert body["image"]["id"]
    assert body["extraction"]["image_analysis_status"] == "COMPLETED"
    assert body["extraction"]["image_cues"] == [{
        "cue": "Water_Disaster",
        "confidence": 0.91,
        "evidence": "Predicted by the local image classifier",
    }]
    assert body["extraction"]["extracted_facts"]["incident_category"] is None
    assert "image_context" in body["extraction"]["evidence"]
    assert "Water_Disaster" in body["extraction"]["evidence"]["image_context"][0]
    assert "incident_category" not in body["extraction"]["confidence"]


def test_failed_analysis_of_later_image_keeps_report_and_image(client, valid_form, monkeypatch):
    from app.services import extraction_service

    report = client.post("/reports", data=valid_form).json()
    monkeypatch.setattr(extraction_service, "analyze_image", lambda *_: ("FAILED", None))
    response = client.post(
        f"/reports/{report['id']}/media",
        files={"image": ("evidence.png", PNG, "image/png")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == report["id"]
    assert body["description"] == report["description"]
    assert body["image"]["id"]
    assert body["extraction"]["image_analysis_status"] == "FAILED"
    assert body["extraction"]["image_cues"] is None


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
