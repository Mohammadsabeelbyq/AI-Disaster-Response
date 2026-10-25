import uuid

from app.database import SessionLocal
from app.models.resources import ResourceAvailabilityEvent


def _login(client, role):
    client.post("/auth/logout")
    credentials = {
        "USER": ("user@example.test", "test-user-password-123"),
        "MANAGEMENT": ("coordinator@example.test", "test-coordinator-password-123"),
        "ADMIN": ("admin@example.test", "test-admin-password-123"),
    }[role]
    return client.post("/auth/login", json={
        "email": credentials[0],
        "password": credentials[1],
        "role": role,
    })


def _resource_payload(department_id, **overrides):
    return {
        "code": "RES-TEAM-01",
        "department_id": department_id,
        "resource_type": "RESCUE_TEAM",
        "name": "North rescue team",
        "capabilities": ["RESCUE", "FLOOD_RESCUE"],
        "latitude": 10.01,
        "longitude": 76.31,
        "availability": "AVAILABLE",
        **overrides,
    }


def test_admin_registers_resources_and_coordinator_audits_availability(client, valid_form):
    assert _login(client, "MANAGEMENT").status_code == 200
    assert client.post("/departments", json={
        "code": "DEP-FIRE",
        "name": "Fire and Rescue",
        "department_type": "FIRE",
    }).status_code == 403

    assert _login(client, "ADMIN").status_code == 200
    department_response = client.post("/departments", json={
        "code": "dep-fire",
        "name": "Fire and Rescue",
        "department_type": "FIRE",
    })
    assert department_response.status_code == 201, department_response.text
    department = department_response.json()
    assert department["code"] == "DEP-FIRE"

    duplicate_department = client.post("/departments", json={
        "code": "DEP-FIRE",
        "name": "Duplicate",
        "department_type": "FIRE",
    })
    assert duplicate_department.status_code == 409

    resource_response = client.post(
        "/resources", json=_resource_payload(department["id"]))
    assert resource_response.status_code == 201, resource_response.text
    resource = resource_response.json()
    assert resource["code"] == "RES-TEAM-01"
    assert resource["capabilities"] == ["RESCUE", "FLOOD_RESCUE"]
    assert resource["availability"] == "AVAILABLE"
    assert resource["availability_events"][0]["previous_availability"] is None

    assert client.post(
        "/resources", json=_resource_payload(department["id"])).status_code == 409
    assert client.get("/resources?availability=AVAILABLE").json()[0]["id"] == resource["id"]
    assert client.get(f"/resources/{resource['id']}").status_code == 200

    assert _login(client, "MANAGEMENT").status_code == 200
    changed = client.patch(f"/resources/{resource['id']}/availability", json={
        "availability": "UNAVAILABLE",
        "reason": "Team is undergoing equipment checks.",
    })
    assert changed.status_code == 200, changed.text
    assert changed.json()["availability"] == "UNAVAILABLE"
    assert client.get("/resources?availability=AVAILABLE").json() == []
    assert client.get("/resources?availability=UNAVAILABLE").json()[0]["id"] == resource["id"]

    with SessionLocal() as db:
        events = db.query(ResourceAvailabilityEvent).filter_by(
            resource_id=uuid.UUID(resource["id"]),
        ).order_by(ResourceAvailabilityEvent.changed_at).all()
        assert [event.new_availability for event in events] == ["AVAILABLE", "UNAVAILABLE"]
        assert events[-1].previous_availability == "AVAILABLE"
        assert events[-1].reason == "Team is undergoing equipment checks."

    unchanged = client.patch(f"/resources/{resource['id']}/availability", json={
        "availability": "UNAVAILABLE",
        "reason": "Repeated status.",
    })
    assert unchanged.status_code == 409


def test_resource_candidates_in_response_plan_use_registered_current_state(client, valid_form):
    report_data = {
        **valid_form,
        "description": "Flood water rising; 12 people are trapped and need rescue.",
    }
    report = client.post("/reports", data=report_data).json()

    assert _login(client, "ADMIN").status_code == 200
    department = client.post("/departments", json={
        "code": "DEP-RESCUE",
        "name": "Rescue Services",
        "department_type": "DISASTER_MANAGEMENT",
    }).json()
    available = client.post("/resources", json=_resource_payload(
        department["id"], code="RES-AVAILABLE", capabilities=["RESCUE"])).json()
    unavailable = client.post("/resources", json=_resource_payload(
        department["id"], code="RES-UNAVAILABLE", capabilities=["RESCUE"],
        availability="UNAVAILABLE")).json()

    assert _login(client, "MANAGEMENT").status_code == 200
    incident = client.post(f"/reports/{report['id']}/confirm").json()
    plan = client.post(f"/incidents/{incident['id']}/plans")
    assert plan.status_code == 201, plan.text
    candidates = plan.json()["resource_candidates"]
    assert [candidate["code"] for candidate in candidates] == ["RES-AVAILABLE"]
    assert candidates[0]["id"] == available["id"]
    assert candidates[0]["matched_capabilities"] == ["RESCUE"]
    assert unavailable["id"] not in {candidate["id"] for candidate in candidates}

    changed = client.patch(f"/resources/{available['id']}/availability", json={
        "availability": "UNAVAILABLE",
        "reason": "Demonstration of a live state change.",
    })
    assert changed.status_code == 200
    next_plan = client.post(f"/incidents/{incident['id']}/plans")
    assert next_plan.status_code == 201
    assert next_plan.json()["resource_candidates"] == []

    assert _login(client, "USER").status_code == 200
    assert client.get("/resources").status_code == 403


def test_plan_capability_gaps_include_all_matching_registry_resources(client, valid_form):
    assert _login(client, "USER").status_code == 200
    report = client.post("/reports", data={
        **valid_form,
        "disaster_type": "OTHER",
        "description": "Requesting rescue and medical support.",
    }).json()

    assert _login(client, "ADMIN").status_code == 200
    department_response = client.post("/departments", json={
        "code": "DEP-MEDICAL",
        "name": "Medical Response",
        "department_type": "MEDICAL",
    })
    assert department_response.status_code == 201
    department = department_response.json()
    rescue_response = client.post("/resources", json=_resource_payload(
        department["id"], code="RES-RESCUE", capabilities=["RESCUE"]
    ))
    medical_response = client.post("/resources", json=_resource_payload(
        department["id"], code="RES-MEDICAL", capabilities=["MEDICAL"]
    ))
    assert rescue_response.status_code == 201, rescue_response.text
    assert medical_response.status_code == 201, medical_response.text

    assert _login(client, "MANAGEMENT").status_code == 200
    facts = {**report["extraction"]["extracted_facts"],
             "requested_assistance": ["RESCUE", "MEDICAL"]}
    assert client.patch(f"/reports/{report['id']}/extraction", json={
        "facts": facts,
    }).status_code == 200
    incident = client.post(f"/reports/{report['id']}/confirm").json()

    plan = client.post(f"/incidents/{incident['id']}/plans")
    assert plan.status_code == 201, plan.text
    assert not any(
        "Unmet incident capability requirements" in gap
        for gap in plan.json()["gaps"]
    )


def test_nearby_resources_use_active_registry_capabilities_and_current_availability(client, valid_form):
    assert _login(client, "USER").status_code == 200
    report = client.post("/reports", data={
        **valid_form,
        "description": "Flood water is rising; rescue support is needed.",
    }).json()

    assert _login(client, "ADMIN").status_code == 200
    department = client.post("/departments", json={
        "code": "DEP-NEARBY",
        "name": "Nearby Response",
        "department_type": "DISASTER_MANAGEMENT",
    }).json()
    available = client.post("/resources", json=_resource_payload(
        department["id"], code="RES-NEARBY-AVAILABLE", capabilities=["RESCUE"]
    )).json()
    unavailable = client.post("/resources", json=_resource_payload(
        department["id"], code="RES-NEARBY-UNAVAILABLE", capabilities=["RESCUE"],
        availability="UNAVAILABLE",
    )).json()
    far_away = client.post("/resources", json=_resource_payload(
        department["id"], code="RES-FAR-AWAY", capabilities=["RESCUE"],
        latitude=80.0,
    )).json()

    assert _login(client, "MANAGEMENT").status_code == 200
    facts = {**report["extraction"]["extracted_facts"],
             "requested_assistance": ["RESCUE"]}
    assert client.patch(f"/reports/{report['id']}/extraction", json={
        "facts": facts,
    }).status_code == 200
    incident = client.post(f"/reports/{report['id']}/confirm").json()

    response = client.get(
        f"/incidents/{incident['id']}/resources?status=AVAILABLE&status=UNAVAILABLE")
    assert response.status_code == 200, response.text
    resources = response.json()["resources"]
    assert {item["id"] for item in resources} == {available["id"], unavailable["id"]}
    assert {item["availability"] for item in resources} == {"AVAILABLE", "UNAVAILABLE"}
    assert all(item["department_name"] == department["name"] for item in resources)
    assert far_away["id"] not in {item["id"] for item in resources}
