from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

from app.database import SessionLocal
from app.models.incident import WorkflowAudit
from app.models.report import IncidentReport
from app.models.report_relationship import ReportRelationshipRecord
from tests.conftest import rec


def _sign_in_coordinator(client):
    client.post("/auth/logout")
    response = client.post("/auth/login", json={
        "email": "coordinator@example.test",
        "password": "test-coordinator-password-123",
        "role": "MANAGEMENT",
    })
    assert response.status_code == 200
    return response.json()["id"]


def test_report_relationship_detection_and_decisions_are_human_reviewed(client):
    source = client.post("/reports/import/json", json=[rec()]).json()
    other = client.post("/reports/import/json", json=[rec(
        description="Fire reported near the same area",
        latitude=10.001,
        longitude=76.301,
    )]).json()
    source_id = source["results"][0]["reportId"]
    other_id = other["results"][0]["reportId"]
    actor_id = _sign_in_coordinator(client)

    detected = client.post(f"/reports/{source_id}/potential-relationships")
    assert detected.status_code == 200, detected.text
    proposals = detected.json()
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal["status"] == "PROPOSED"
    assert {proposal["report"]["id"], proposal["related_report"]["id"]} == {
        source_id, other_id,
    }
    assert proposal["evidence"]["time_difference_hours"] < 24
    assert proposal["evidence"]["distance_km"] < 25
    assert proposal["evidence"]["semantic_matching_enabled"] is False
    assert proposal["evidence"]["semantic_similarity"] is None

    repeated = client.post(f"/reports/{source_id}/potential-relationships")
    assert repeated.status_code == 200
    assert repeated.json()[0]["id"] == proposal["id"]
    assert len(client.get("/report-relationships").json()) == 1

    confirmed = client.post(
        f"/report-relationships/{proposal['id']}/confirm",
        json={"reason": "Same flooding event."},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "CONFIRMED"
    assert confirmed.json()["decided_by"] == actor_id
    assert confirmed.json()["decided_at"]
    assert confirmed.json()["decision_reason"] == "Same flooding event."

    assert client.get(f"/reports/{source_id}").json()["status"] == "SUBMITTED"
    assert client.get(f"/reports/{other_id}").json()["status"] == "SUBMITTED"
    assert client.get("/incidents").json() == []
    assert client.get("/report-relationships?status=CONFIRMED").json()[0]["id"] == proposal["id"]
    assert client.post(
        f"/report-relationships/{proposal['id']}/reject", json={}
    ).status_code == 409

    with SessionLocal() as db:
        record = db.get(ReportRelationshipRecord, UUID(proposal["id"]))
        assert record.status == "CONFIRMED"
        audit = db.query(WorkflowAudit).filter_by(
            event_type="REPORT_RELATIONSHIP_CONFIRMED",
            report_id=UUID(proposal["report"]["id"]),
        ).one()
        assert audit.actor_id == UUID(actor_id)
        assert audit.details["related_report_id"] == proposal["related_report"]["id"]


def test_detection_applies_time_and_distance_windows(client):
    source = client.post("/reports/import/json", json=[rec()]).json()
    nearby = client.post("/reports/import/json", json=[rec(
        description="Nearby report",
        latitude=10.001,
        longitude=76.301,
    )]).json()
    far = client.post("/reports/import/json", json=[rec(
        description="Distant report",
        latitude=11,
        longitude=77,
    )]).json()
    source_id = source["results"][0]["reportId"]
    nearby_id = nearby["results"][0]["reportId"]
    far_id = far["results"][0]["reportId"]
    with SessionLocal() as db:
        old_report = db.get(IncidentReport, UUID(nearby_id))
        old_report.submitted_at = datetime.now(timezone.utc) - timedelta(days=3)
        db.commit()

    _sign_in_coordinator(client)
    detected = client.post(f"/reports/{source_id}/potential-relationships")
    assert detected.status_code == 200, detected.text
    assert detected.json() == []
    assert client.get(f"/reports/{far_id}").status_code == 200


def test_semantic_similarity_is_included_when_enabled(client, monkeypatch):
    import app.services.report_relationship_service as service

    source = client.post("/reports/import/json", json=[rec()]).json()
    other = client.post("/reports/import/json", json=[rec(
        description="A similar emergency description",
        latitude=10.001,
        longitude=76.301,
    )]).json()
    source_id = source["results"][0]["reportId"]
    other_id = other["results"][0]["reportId"]
    _sign_in_coordinator(client)
    monkeypatch.setattr(service, "get_settings", lambda: SimpleNamespace(
        report_relationship_time_window_hours=24,
        report_relationship_radius_km=25,
        semantic_report_matching_enabled=True,
    ))
    monkeypatch.setattr(service, "_semantic_scores", lambda _source, candidates: [
        0.8765 for _ in candidates
    ])

    detected = client.post(f"/reports/{source_id}/potential-relationships")
    assert detected.status_code == 200, detected.text
    relationship = next(
        item for item in detected.json()
        if other_id in (item["report"]["id"], item["related_report"]["id"])
    )
    assert relationship["evidence"]["semantic_matching_enabled"] is True
    assert relationship["evidence"]["semantic_similarity"] == 0.8765


def test_rejected_relationship_is_recorded_and_not_reproposed(client):
    source = client.post("/reports/import/json", json=[rec()]).json()
    other = client.post("/reports/import/json", json=[rec(
        description="Another nearby report",
        latitude=10.001,
        longitude=76.301,
    )]).json()
    source_id = source["results"][0]["reportId"]
    _sign_in_coordinator(client)

    detected = client.post(f"/reports/{source_id}/potential-relationships").json()
    rejected = client.post(
        f"/report-relationships/{detected[0]['id']}/reject",
        json={"reason": "Different incident after review."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["decided_by"]
    assert rejected.json()["decided_at"]
    assert rejected.json()["decision_reason"] == "Different incident after review."
    assert client.post(f"/reports/{source_id}/potential-relationships").json() == []
    assert client.get("/report-relationships?status=REJECTED").json()[0]["id"] == detected[0]["id"]
    assert client.get(f"/reports/{source_id}").json()["status"] == "SUBMITTED"
    assert client.get(f"/reports/{other['results'][0]['reportId']}").json()["status"] == "SUBMITTED"


def test_reporters_cannot_detect_or_review_relationships(client):
    source = client.post("/reports/import/json", json=[rec()]).json()
    report_id = source["results"][0]["reportId"]

    assert client.post(f"/reports/{report_id}/potential-relationships").status_code == 403
    assert client.get("/report-relationships").status_code == 403
