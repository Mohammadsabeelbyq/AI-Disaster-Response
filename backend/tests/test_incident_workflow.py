import uuid

from app.database import SessionLocal
from app.models.incident import WorkflowAudit


def _login_coordinator(client):
    client.post("/auth/logout")
    return client.post("/auth/login", json={
        "email": "coordinator@example.test",
        "password": "test-coordinator-password-123",
        "role": "MANAGEMENT",
    })


def test_coordinator_confirms_report_generates_grounded_plan_and_approves(client, valid_form):
    submitted = client.post("/reports", data=valid_form).json()
    assert _login_coordinator(client).status_code == 200

    review = client.post(f"/reports/{submitted['id']}/review")
    assert review.status_code == 200
    assert review.json()["status"] == "UNDER_REVIEW"

    corrected = {**submitted["extraction"]["extracted_facts"]}
    corrected.update({
        "urgency": "CRITICAL",
        "hazards": ["FLOODWATER"],
        "requested_assistance": ["RESCUE", "WATER"],
        "location_mentions": ["Edappally"],
    })
    correction_response = client.patch(
        f"/reports/{submitted['id']}/extraction", json={"facts": corrected})
    assert correction_response.status_code == 200

    confirmed = client.post(f"/reports/{submitted['id']}/confirm")
    assert confirmed.status_code == 201
    incident = confirmed.json()
    assert incident["report_id"] == submitted["id"]
    assert incident["status"] == "CONFIRMED"
    assert client.get(f"/reports/{submitted['id']}").json()["status"] == "ACCEPTED"
    assert client.post(f"/reports/{submitted['id']}/confirm").status_code == 409

    generated = client.post(f"/incidents/{incident['id']}/plans")
    assert generated.status_code == 201
    plan = generated.json()
    assert plan["status"] == "AWAITING_APPROVAL"
    assert plan["source_facts"] == corrected
    assert plan["human_approval_required"] is True
    assert plan["resource_candidates"] == []
    assert any("no specific responders" in gap for gap in plan["gaps"])
    assert any("life-safety" in action for action in plan["recommended_actions"])
    assert any("rescue" in action for action in plan["recommended_actions"])

    fetched_incident = client.get(f"/incidents/{incident['id']}")
    assert fetched_incident.status_code == 200
    assert fetched_incident.json()["plans"][0]["id"] == plan["id"]

    approved = client.post(
        f"/response-plans/{plan['id']}/approve",
        json={"reason": "Coordinator reviewed current evidence."},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["human_approval_required"] is True
    assert approved.json()["decided_by"] == incident["confirmed_by"]
    assert approved.json()["decided_at"]
    assert approved.json()["decision_reason"] == "Coordinator reviewed current evidence."
    assert client.post(f"/response-plans/{plan['id']}/approve", json={}).status_code == 409

    with SessionLocal() as db:
        events = db.query(WorkflowAudit).filter(
            (WorkflowAudit.report_id == uuid.UUID(submitted["id"]))
            | (WorkflowAudit.incident_id == uuid.UUID(incident["id"]))
        ).order_by(WorkflowAudit.created_at).all()
        assert [event.event_type for event in events] == [
            "REPORT_REVIEW_STARTED", "INCIDENT_CONFIRMED",
            "RESPONSE_PLAN_GENERATED", "RESPONSE_PLAN_APPROVED",
        ]
        assert all(event.actor_id == uuid.UUID(incident["confirmed_by"]) for event in events)
        assert events[-1].plan_id == uuid.UUID(plan["id"])


def test_dismissed_report_cannot_be_confirmed_or_planned(client, valid_form):
    report = client.post("/reports", data=valid_form).json()
    assert _login_coordinator(client).status_code == 200
    assert client.post(f"/reports/{report['id']}/review").json()["status"] == "UNDER_REVIEW"

    dismissed = client.post(
        f"/reports/{report['id']}/dismiss", json={"reason": "Duplicate report."})
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "DISMISSED"
    assert dismissed.json()["incident"] is None
    assert client.post(f"/reports/{report['id']}/confirm").status_code == 409

    with SessionLocal() as db:
        events = db.query(WorkflowAudit).filter_by(
            report_id=uuid.UUID(report["id"])).all()
        assert [event.event_type for event in events] == [
            "REPORT_REVIEW_STARTED", "REPORT_DISMISSED",
        ]
        assert events[1].details["reason"] == "Duplicate report."


def test_user_cannot_start_review_or_generate_response_plans(client, valid_form):
    report = client.post("/reports", data=valid_form).json()
    assert client.post(f"/reports/{report['id']}/review").status_code == 403
    assert client.post("/incidents/00000000-0000-0000-0000-000000000000/plans").status_code == 403


def test_admin_can_review_confirm_generate_and_reject_plan(client, valid_form):
    report = client.post("/reports", data=valid_form).json()
    client.post("/auth/logout")
    login = client.post("/auth/login", json={
        "email": "admin@example.test",
        "password": "test-admin-password-123",
        "role": "ADMIN",
    })
    assert login.status_code == 200
    assert client.post(f"/reports/{report['id']}/review").status_code == 200
    incident = client.post(f"/reports/{report['id']}/confirm").json()
    plan = client.post(f"/incidents/{incident['id']}/plans").json()
    rejected = client.post(
        f"/response-plans/{plan['id']}/reject", json={"reason": "Needs more evidence."})
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["decided_by"] == login.json()["id"]