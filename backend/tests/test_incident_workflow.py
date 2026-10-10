import uuid

from app.database import SessionLocal
from app.models.incident import PriorityRuleConfig, WorkflowAudit
from app.services.incident_service import _next_priority_version


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


def test_admin_can_manage_priority_configuration_and_rule_versioning(client, valid_form):
    report = client.post("/reports", data=valid_form).json()
    client.post("/auth/logout")
    admin_login = client.post("/auth/login", json={
        "email": "admin@example.test",
        "password": "test-admin-password-123",
        "role": "ADMIN",
    })
    assert admin_login.status_code == 200

    config = client.post('/priority-configs', json={
        'weights': {
            'life_safety_risk': 0.35,
            'urgency': 0.25,
            'affected_population': 0.2,
            'hazard_level': 0.12,
            'evidence_confidence': 0.08,
        },
        'thresholds': {'CRITICAL': 75, 'HIGH': 55, 'MEDIUM': 30, 'LOW': 0},
        'notes': 'Initial policy version',
    })
    assert config.status_code == 201, config.text
    config_body = config.json()
    assert config_body['version']
    assert config_body['is_active'] is True
    assert config_body['weights']['urgency'] == 0.25

    assert client.post(f"/reports/{report['id']}/review").status_code == 200
    incident = client.post(f"/reports/{report['id']}/confirm").json()
    priority = client.get(f"/incidents/{incident['id']}/priority").json()
    assert priority['priority_rule_version'] == config_body['version']
    assert priority['priority_score'] >= 0
    assert priority['priority_band'] in {'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}
    assert priority['priority_factors']['urgency'] >= 0

    next_config = client.post('/priority-configs', json={
        'weights': {
            'life_safety_risk': 0.2,
            'urgency': 0.2,
            'affected_population': 0.2,
            'hazard_level': 0.2,
            'evidence_confidence': 0.2,
        },
        'thresholds': {'CRITICAL': 90, 'HIGH': 70, 'MEDIUM': 40, 'LOW': 0},
        'notes': 'Updated policy version',
    })
    assert next_config.status_code == 201, next_config.text
    assert next_config.json()['version'] != config_body['version']

    historical_priority = client.get(f"/incidents/{incident['id']}/priority").json()
    assert historical_priority['priority_rule_version'] == config_body['version']
    assert historical_priority['priority_score'] == priority['priority_score']
    assert historical_priority['priority_band'] == priority['priority_band']

    next_report = client.post('/reports', data=valid_form).json()
    assert client.post(f"/reports/{next_report['id']}/review").status_code == 200
    next_incident = client.post(f"/reports/{next_report['id']}/confirm").json()
    next_priority = client.get(f"/incidents/{next_incident['id']}/priority").json()
    assert next_priority['priority_rule_version'] == next_config.json()['version']

    invalid = client.post('/priority-configs', json={
        'weights': {'life_safety_risk': 0.6, 'urgency': 0.6},
        'thresholds': {'CRITICAL': 50, 'HIGH': 30, 'MEDIUM': 20, 'LOW': 10},
    })
    assert invalid.status_code == 422


def test_coordinator_can_override_priority_with_reason_and_traceability(client, valid_form):
    report = client.post("/reports", data=valid_form).json()
    assert _login_coordinator(client).status_code == 200
    assert client.post(f"/reports/{report['id']}/review").status_code == 200
    incident = client.post(f"/reports/{report['id']}/confirm").json()
    priority = client.get(f"/incidents/{incident['id']}/priority").json()
    assert priority['priority_is_overridden'] is False

    override = client.post(
        f"/incidents/{incident['id']}/priority/override",
        json={"reason": "Human review identified a higher risk than the score suggests."},
    )
    assert override.status_code == 200
    final = override.json()
    assert final['priority_is_overridden'] is True
    assert final['priority_override_reason'] == 'Human review identified a higher risk than the score suggests.'
    assert final['priority_override_by'] == final['confirmed_by']
    assert final['priority_override_at']
    assert final['priority_original_score'] == priority['priority_score']
    assert final['priority_original_band'] == priority['priority_band']
    assert final['priority_band'] in {'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}

    missing_reason = client.post(f"/incidents/{incident['id']}/priority/override", json={"reason": "   "})
    assert missing_reason.status_code == 422


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


def test_priority_policy_versions_increment_numerically(client):
    admin = client.post("/auth/login", json={
        "email": "admin@example.test",
        "password": "test-admin-password-123",
        "role": "ADMIN",
    })
    assert admin.status_code == 200

    with SessionLocal() as db:
        db.add_all([
            PriorityRuleConfig(version="v9", weights={}, thresholds={}, created_by=uuid.UUID(admin.json()["id"])),
            PriorityRuleConfig(version="v10", weights={}, thresholds={}, created_by=uuid.UUID(admin.json()["id"])),
        ])
        db.commit()
        assert _next_priority_version(db) == "v11"