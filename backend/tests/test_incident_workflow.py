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
    assert any("No available registered resource" in gap for gap in plan["gaps"])
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


def test_coordinator_links_report_without_changing_its_original_source(client, valid_form):
    primary = client.post("/reports", data=valid_form).json()
    related = client.post("/reports", data={
        **valid_form,
        "description": "A second caller reports water at the same location.",
    }).json()
    assert _login_coordinator(client).status_code == 200
    assert client.post(f"/reports/{primary['id']}/review").status_code == 200
    incident = client.post(f"/reports/{primary['id']}/confirm").json()

    linked = client.post(
        f"/incidents/{incident['id']}/reports/{related['id']}/link",
        json={"reason": "Same location and same flooding event."},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["report_links"][0]["report_id"] == related["id"]
    assert linked.json()["report_links"][0]["relationship_type"] == "LINKED_REPORT"

    fetched = client.get(f"/reports/{related['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["description"] == "A second caller reports water at the same location."
    assert fetched.json()["status"] == "LINKED"
    assert fetched.json()["incident_links"][0]["incident_id"] == incident["id"]
    assert client.get(f"/reports/{primary['id']}").json()["description"] == valid_form["description"]

    with SessionLocal() as db:
        event = db.query(WorkflowAudit).filter_by(
            event_type="REPORT_LINKED_TO_INCIDENT",
            report_id=uuid.UUID(related["id"]),
        ).one()
        assert event.incident_id == uuid.UUID(incident["id"])
        assert event.details["reason"] == "Same location and same flooding event."

    assert client.post(
        f"/incidents/{incident['id']}/reports/{related['id']}/link",
        json={"reason": "Duplicate attempt."},
    ).status_code == 409


def test_coordinator_merges_incidents_and_keeps_both_original_reports(client, valid_form):
    primary = client.post("/reports", data=valid_form).json()
    duplicate = client.post("/reports", data={
        **valid_form,
        "description": "Another original source report for the same flood.",
    }).json()
    assert _login_coordinator(client).status_code == 200
    for report in (primary, duplicate):
        assert client.post(f"/reports/{report['id']}/review").status_code == 200
    canonical = client.post(f"/reports/{primary['id']}/confirm").json()
    duplicate_incident = client.post(f"/reports/{duplicate['id']}/confirm").json()

    merged = client.post(
        f"/incidents/{duplicate_incident['id']}/merge-into/{canonical['id']}",
        json={"reason": "Coordinator verified both reports describe one flood."},
    )
    assert merged.status_code == 200, merged.text
    relation = merged.json()["report_links"][0]
    assert relation["report_id"] == duplicate["id"]
    assert relation["source_incident_id"] == duplicate_incident["id"]
    assert relation["relationship_type"] == "MERGED_INCIDENT"

    original_report = client.get(f"/reports/{duplicate['id']}")
    assert original_report.status_code == 200
    assert original_report.json()["description"] == "Another original source report for the same flood."
    assert original_report.json()["incident"]["id"] == duplicate_incident["id"]
    assert original_report.json()["incident"]["status"] == "MERGED"
    assert original_report.json()["incident"]["merged_into_id"] == canonical["id"]
    assert original_report.json()["incident_links"][0]["incident_id"] == canonical["id"]

    assert duplicate_incident["id"] not in {
        item["id"] for item in client.get("/incidents").json()
    }
    archived = client.get(f"/incidents/{duplicate_incident['id']}")
    assert archived.status_code == 200
    assert archived.json()["status"] == "MERGED"
    assert archived.json()["merged_into_id"] == canonical["id"]

    assert client.post("/auth/logout").status_code == 204
    assert client.post("/auth/login", json={
        "email": "user@example.test",
        "password": "test-user-password-123",
        "role": "USER",
    }).status_code == 200
    reporter_view = client.get(f"/reports/{duplicate['id']}")
    assert reporter_view.status_code == 200
    assert reporter_view.json()["description"] == "Another original source report for the same flood."
    assert reporter_view.json()["incident_links"] == []
    assert reporter_view.json()["incident"]["merged_into_id"] is None

    assert _login_coordinator(client).status_code == 200
    with SessionLocal() as db:
        event = db.query(WorkflowAudit).filter_by(
            event_type="INCIDENT_MERGED",
            incident_id=uuid.UUID(canonical["id"]),
        ).one()
        assert event.details["source_incident_id"] == duplicate_incident["id"]
        assert event.details["reason"] == "Coordinator verified both reports describe one flood."


def test_admin_can_manage_priority_configuration_and_rule_versioning(client, valid_form):
    valid_form["description"] = "Flood water is rising; 12 people are trapped and need rescue."
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
    assert priority['priority_factors']['urgency'] == 1.0
    assert priority['priority_factors']['hazard_level'] >= 0

    next_config = client.post('/priority-configs', json={
        'weights': {
            'life_safety_risk': 0.2,
            'urgency': 0.2,
            'affected_population': 0.2,
            'hazard_level': 0.2,
            'evidence_confidence': 0.2,
        },
        'thresholds': {'CRITICAL': 90, 'HIGH': 80, 'MEDIUM': 40, 'LOW': 0},
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
    assert next_priority['priority_score'] != priority['priority_score']
    assert priority['priority_band'] == 'CRITICAL'
    assert next_priority['priority_band'] == 'HIGH'

    invalid = client.post('/priority-configs', json={
        'weights': {'life_safety_risk': 0.6, 'urgency': 0.6},
        'thresholds': {'CRITICAL': 50, 'HIGH': 30, 'MEDIUM': 20, 'LOW': 10},
    })
    assert invalid.status_code == 422

    invalid_boundaries = client.post('/priority-configs', json={
        'weights': {
            'life_safety_risk': 0.35,
            'urgency': 0.25,
            'affected_population': 0.2,
            'hazard_level': 0.12,
            'evidence_confidence': 0.08,
        },
        'thresholds': {'CRITICAL': 75, 'HIGH': 75, 'MEDIUM': 30, 'LOW': 0},
    })
    assert invalid_boundaries.status_code == 422


def test_confirmed_incident_persists_advisory_score_classification_and_factors(client, valid_form):
    from app.models.incident import Incident

    valid_form["description"] = "Flood water is rising; 12 people are trapped and need rescue."
    report = client.post("/reports", data=valid_form).json()
    submitted_description = report["description"]
    submitted_facts = report["extraction"]["extracted_facts"]
    assert _login_coordinator(client).status_code == 200
    assert client.post(f"/reports/{report['id']}/review").status_code == 200

    response = client.post(f"/reports/{report['id']}/confirm")
    assert response.status_code == 201
    body = response.json()
    assert body["priority_score"] is not None
    assert body["priority_band"] in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    assert body["priority_factors"]["urgency"] == 1.0
    assert body["priority_factors"]["life_safety_risk"] == 1.0
    assert body["priority_rule_version"]
    assert body["priority_algorithm_version"] == "priority-v1"
    assert body["priority_breakdown"]["final_score"] == body["priority_score"]
    assert body["priority_breakdown"]["risk_factors"]["urgency"]["score_points"] > 0
    assert body["priority_is_advisory"] is True
    saved_report = client.get(f"/reports/{report['id']}").json()
    assert saved_report["description"] == submitted_description
    assert saved_report["extraction"]["extracted_facts"] == submitted_facts

    persisted = client.get(f"/incidents/{body['id']}/priority").json()
    assert persisted["priority_score"] == body["priority_score"]
    assert persisted["priority_band"] == body["priority_band"]
    assert persisted["priority_factors"] == body["priority_factors"]
    assert persisted["priority_rule_version"] == body["priority_rule_version"]
    assert persisted["priority_algorithm_version"] == body["priority_algorithm_version"]
    assert persisted["priority_breakdown"] == body["priority_breakdown"]
    with SessionLocal() as db:
        stored = db.get(Incident, uuid.UUID(body["id"]))
        assert stored.priority_score == body["priority_score"]
        assert stored.priority_band == body["priority_band"]
        assert stored.priority_factors == body["priority_factors"]
        assert stored.priority_rule_version == body["priority_rule_version"]
        assert stored.priority_algorithm_version == body["priority_algorithm_version"]
        assert stored.priority_breakdown == body["priority_breakdown"]
        assert stored.priority_calculated_at is not None


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
    assert client.get("/incidents").status_code == 403
    assert client.post("/incidents/00000000-0000-0000-0000-000000000000/plans").status_code == 403


def test_incident_list_includes_saved_report_location_and_latest_priority(client, valid_form):
    report = client.post("/reports", data=valid_form).json()
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/incidents").status_code == 401
    assert _login_coordinator(client).status_code == 200
    assert client.post(f"/reports/{report['id']}/review").status_code == 200
    incident = client.post(f"/reports/{report['id']}/confirm").json()

    listed = client.get("/incidents")
    assert listed.status_code == 200
    map_incident = listed.json()[0]
    assert map_incident["id"] == incident["id"]
    assert map_incident["report"] == {
        "id": report["id"],
        "disaster_type": "FLOOD",
        "description": report["description"],
        "latitude": 10.027,
        "longitude": 76.308,
        "location_name": "Edappally",
    }
    assert map_incident["status"] == "CONFIRMED"
    assert map_incident["priority_band"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    updated = client.post(
        f"/incidents/{incident['id']}/priority/override",
        json={"reason": "Current field assessment", "band": "CRITICAL"},
    )
    assert updated.status_code == 200
    assert client.get("/incidents").json()[0]["priority_band"] == "CRITICAL"


def test_incident_list_includes_valid_coordinates_without_location_name(client, valid_form):
    form_without_place = {key: value for key, value in valid_form.items() if key != "location_name"}
    report = client.post("/reports", data=form_without_place).json()
    assert report["location_name"] is None
    assert _login_coordinator(client).status_code == 200
    assert client.post(f"/reports/{report['id']}/review").status_code == 200
    incident = client.post(f"/reports/{report['id']}/confirm").json()

    response = client.get("/incidents")
    assert response.status_code == 200
    mapped_incident = next(item for item in response.json() if item["id"] == incident["id"])
    assert mapped_incident["report"]["latitude"] == 10.027
    assert mapped_incident["report"]["longitude"] == 76.308
    assert mapped_incident["report"]["location_name"] is None


def test_saved_location_correction_moves_incident_map_coordinates(client, valid_form):
    report = client.post("/reports", data=valid_form).json()
    assert _login_coordinator(client).status_code == 200
    assert client.post(f"/reports/{report['id']}/review").status_code == 200
    incident = client.post(f"/reports/{report['id']}/confirm").json()

    correction = client.patch(f"/reports/{report['id']}/location", json={
        "latitude": -33.8688,
        "longitude": 151.2093,
        "location_name": "Sydney",
    })
    assert correction.status_code == 200
    assert correction.json()["latitude"] == 10.027
    assert correction.json()["longitude"] == 76.308

    mapped = client.get("/incidents").json()
    updated_incident = next(item for item in mapped if item["id"] == incident["id"])
    assert updated_incident["report"]["latitude"] == -33.8688
    assert updated_incident["report"]["longitude"] == 151.2093
    assert updated_incident["report"]["location_name"] == "Sydney"


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