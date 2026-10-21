"""Unit and integration tests for FR-28 (Planner Grounding) and FR-29 (Rationale & Evidence)."""
import uuid
import pytest
from app.database import SessionLocal
from app.models.incident import ResponsePlan
from app.models.resource import RegisteredResource
from app.services import incident_service


def _login(client, email, password, role):
    client.post("/auth/logout")
    return client.post("/auth/login", json={
        "email": email,
        "password": password,
        "role": role,
    })


def _create_confirmed_incident(client, disaster_type="FLOOD", latitude=10.027, longitude=76.308,
                               requested_assistance=None, hazards=None):
    _login(client, "user@example.test", "test-user-password-123", "USER")
    form_data = {
        "disaster_type": disaster_type,
        "description": f"Incident requiring assistance at {latitude}, {longitude}",
        "latitude": str(latitude),
        "longitude": str(longitude),
        "location_name": "Test Location",
    }
    report = client.post("/reports", data=form_data).json()
    assert "id" in report, f"Report submission failed: {report}"

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    client.post(f"/reports/{report['id']}/review")

    # If requested assistance or hazards specified, patch them into effective extraction
    facts = {**report["extraction"]["extracted_facts"]}
    if requested_assistance is not None:
        facts["requested_assistance"] = requested_assistance
    if hazards is not None:
        facts["hazards"] = hazards
    client.patch(f"/reports/{report['id']}/extraction", json={"facts": facts})

    confirmed = client.post(f"/reports/{report['id']}/confirm")
    assert confirmed.status_code == 201, confirmed.text
    return confirmed.json()


def _register_resource(client, name, capabilities, latitude=10.027, longitude=76.308,
                       status="AVAILABLE", resource_type="Rescue Unit"):
    _login(client, "admin@example.test", "test-admin-password-123", "ADMIN")
    payload = {
        "name": name,
        "capabilities": capabilities,
        "status": status,
        "resource_type": resource_type,
    }
    if latitude is not None and longitude is not None:
        payload["latitude"] = latitude
        payload["longitude"] = longitude
    res = client.post("/resources", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_available_and_suitable_resources_are_recommended(client):
    """FR-28: Available and suitable resources are recommended with structured details."""
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE", "WATER"]
    )
    res1 = _register_resource(
        client, "Marine Unit Alpha", ["RESCUE", "WATER_RESCUE"],
        latitude=10.030, longitude=76.310, status="AVAILABLE", resource_type="Rescue Boat"
    )

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201, response.text
    plan = response.json()

    # Verify structured response format
    assert plan["incident_id"] == incident["id"]
    assert "response_option" in plan
    assert "resources" in plan["response_option"]
    assert "constraints_considered" in plan
    assert "rationale" in plan
    assert "evidence" in plan

    # Verify recommended resource
    rec_resources = plan["response_option"]["resources"]
    assert len(rec_resources) == 1
    assert rec_resources[0]["resource_id"] == res1["id"]
    assert rec_resources[0]["name"] == "Marine Unit Alpha"
    assert rec_resources[0]["type"] == "Rescue Boat"
    assert rec_resources[0]["status"] == "available"
    assert "RESCUE" in rec_resources[0]["capabilities"]

    # Verify resource_candidates compatibility
    assert len(plan["resource_candidates"]) == 1
    assert plan["resource_candidates"][0]["resource_id"] == res1["id"]

    # Constraints considered
    assert "Required capability" in plan["constraints_considered"]
    assert "Resource availability" in plan["constraints_considered"]
    assert "Location" in plan["constraints_considered"]


def test_unavailable_resources_are_excluded(client):
    """FR-28: Unavailable resources (status UNAVAILABLE) must not be recommended."""
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"]
    )
    _register_resource(
        client, "Broken Boat", ["RESCUE", "WATER_RESCUE"],
        latitude=10.028, longitude=76.309, status="UNAVAILABLE", resource_type="Boat"
    )

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()

    assert plan["response_option"]["resources"] == []
    assert plan["resource_candidates"] == []
    assert plan["evidence"] == []
    assert "No suitable registered resources were found" in plan["rationale"]
    assert any("no suitable registered resources" in gap.lower() for gap in plan["gaps"])


def test_already_assigned_resources_are_excluded_by_status(client):
    """FR-28: Resources with status BUSY, DEPLOYED, or ASSIGNED are excluded."""
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"]
    )
    _register_resource(client, "Busy Squad", ["RESCUE"], latitude=10.028, longitude=76.309, status="BUSY")
    _register_resource(client, "Deployed Squad", ["RESCUE"], latitude=10.028, longitude=76.309, status="DEPLOYED")

    # Also register one with ASSIGNED in DB directly
    with SessionLocal() as db:
        admin_user = incident_service.get_incident(db, uuid.UUID(incident["id"])).confirmed_by
        assigned_res = RegisteredResource(
            name="Assigned Squad",
            capabilities=["RESCUE"],
            latitude=10.028,
            longitude=76.309,
            status="ASSIGNED",
            created_by=admin_user,
        )
        db.add(assigned_res)
        db.commit()

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()

    assert plan["response_option"]["resources"] == []
    assert plan["resource_candidates"] == []


def test_already_assigned_resources_excluded_by_active_plan(client):
    """FR-28: Resources already assigned to an active response plan are excluded from other incidents."""
    inc1 = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"], latitude=10.0, longitude=76.0
    )
    inc2 = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"], latitude=10.0, longitude=76.0
    )

    shared_res = _register_resource(
        client, "Solo Rescue Unit", ["RESCUE"], latitude=10.0, longitude=76.0, status="AVAILABLE"
    )

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    # Generate plan for Incident 1 which recommends Solo Rescue Unit
    plan1 = client.post(f"/incidents/{inc1['id']}/plans").json()
    assert len(plan1["response_option"]["resources"]) == 1
    assert plan1["response_option"]["resources"][0]["resource_id"] == shared_res["id"]

    # Now generate plan for Incident 2
    plan2 = client.post(f"/incidents/{inc2['id']}/plans").json()
    # Solo Rescue Unit must be excluded because it is already assigned to Incident 1's pending plan
    assert plan2["response_option"]["resources"] == []
    assert plan2["resource_candidates"] == []
    assert "No suitable registered resources were found" in plan2["rationale"]


def test_resources_with_incompatible_capabilities_are_excluded(client):
    """FR-28: Resources that do not meet incident capability requirements are excluded."""
    incident = _create_confirmed_incident(
        client, disaster_type="FIRE", requested_assistance=["FIRE_SUPPRESSION"]
    )
    # Register medical-only resource
    _register_resource(
        client, "Ambulance 101", ["MEDICAL", "MEDICAL_AID"],
        latitude=10.027, longitude=76.308, status="AVAILABLE", resource_type="Ambulance"
    )

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()

    assert plan["response_option"]["resources"] == []
    assert plan["resource_candidates"] == []


def test_resources_violating_location_constraints_are_excluded(client):
    """FR-28: Resources located beyond the search radius are excluded."""
    # Incident at Kochi (10.0, 76.0)
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"], latitude=10.0, longitude=76.0
    )
    # Resource located 250+ km away (~2.5 degrees latitude)
    _register_resource(
        client, "Far Away Rescue", ["RESCUE"],
        latitude=12.5, longitude=76.0, status="AVAILABLE"
    )

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()

    assert plan["response_option"]["resources"] == []
    assert plan["resource_candidates"] == []


def test_unlocated_resources_are_excluded_by_location_constraint(client):
    """FR-28: Resources without location coordinates cannot satisfy location constraints."""
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"]
    )
    _register_resource(
        client, "Unlocated Unit", ["RESCUE"],
        latitude=None, longitude=None, status="AVAILABLE"
    )

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()

    assert plan["response_option"]["resources"] == []


def test_impact_area_radius_constrains_resource_selection(client):
    """FR-28: If incident has an impact area, resources outside the impact area radius are excluded."""
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"], latitude=10.0, longitude=76.0
    )
    # Set an impact area radius of 1,000 metres (1 km)
    client.put(f"/incidents/{incident['id']}/impact-area", json={
        "geometry_type": "RADIUS", "radius_m": 1000
    })

    # Close resource: ~400 metres away (0.0035 degrees lat ~ 389m)
    close_res = _register_resource(
        client, "Near Res", ["RESCUE"], latitude=10.0035, longitude=76.0, status="AVAILABLE"
    )
    # Farther resource: ~3,000 metres away (0.027 degrees lat ~ 3000m)
    far_res = _register_resource(
        client, "Outside Impact Area Res", ["RESCUE"], latitude=10.027, longitude=76.0, status="AVAILABLE"
    )

    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()

    rec_ids = [r["resource_id"] for r in plan["response_option"]["resources"]]
    assert close_res["id"] in rec_ids
    assert far_res["id"] not in rec_ids


def test_no_resource_fabricated_when_no_suitable_resource_exists(client):
    """FR-28: When no suitable resources exist in the database, none are fabricated."""
    incident = _create_confirmed_incident(client, disaster_type="EARTHQUAKE")

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()

    assert plan["response_option"]["resources"] == []
    assert plan["resource_candidates"] == []
    assert plan["evidence"] == []
    assert "No suitable registered resources were found" in plan["rationale"]
    assert any("no suitable registered resources" in gap.lower() for gap in plan["gaps"])


def test_availability_changes_detected_by_final_validation(client):
    """FR-28: Availability changes occurring before finalization are detected and excluded."""
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"], latitude=10.0, longitude=76.0
    )
    res = _register_resource(
        client, "Concurrent Rescue", ["RESCUE"], latitude=10.001, longitude=76.0, status="AVAILABLE"
    )

    # Use SessionLocal to test the final validation hook
    with SessionLocal() as db:
        res_id = uuid.UUID(res["id"])
        inc_id = uuid.UUID(incident["id"])
        coordinator = incident_service.get_incident(db, inc_id).confirmed_by

        def simulate_concurrent_status_change():
            with SessionLocal() as sub_db:
                r = sub_db.get(RegisteredResource, res_id)
                r.status = "UNAVAILABLE"
                sub_db.commit()

        # Generate plan with the pre_finalize_hook triggering the status change
        plan = incident_service.generate_response_plan(
            db, inc_id, coordinator, pre_finalize_hook=simulate_concurrent_status_change
        )

        # The final validation must have detected the change and excluded the resource
        assert plan.response_option["resources"] == []
        assert plan.resource_candidates == []
        assert "No suitable registered resources were found" in plan.rationale


def test_every_recommended_resource_has_rationale_and_traceable_evidence(client):
    """FR-29: Rationale and evidence are grounded in database records and linked to resource_id."""
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE", "WATER"]
    )
    res = _register_resource(
        client, "Coastal Guard 1", ["RESCUE", "WATER_RESCUE"],
        latitude=10.028, longitude=76.309, status="AVAILABLE", resource_type="Patrol Boat"
    )

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()

    # Rationale explains why the resource was selected
    assert "Coastal Guard 1" in plan["rationale"]
    assert "Patrol Boat" in plan["rationale"]
    assert "RESCUE" in plan["rationale"]
    assert "AVAILABLE" in plan["rationale"]

    # Evidence is linked to resource_id and contains traceable facts
    assert len(plan["evidence"]) == 1
    ev = plan["evidence"][0]
    assert ev["resource_id"] == res["id"]
    facts_str = " ".join(ev["facts"])
    assert res["id"] in facts_str
    assert "exists in registered database" in facts_str
    assert "AVAILABLE" in facts_str
    assert "Patrol Boat" in facts_str
    assert "coordinates" in facts_str
    assert "metres" in facts_str


def test_missing_information_is_not_fabricated(client):
    """FR-29: Missing attributes (e.g. resource_type) are treated as Unknown rather than guessed."""
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"]
    )
    # Register resource without resource_type
    _login(client, "admin@example.test", "test-admin-password-123", "ADMIN")
    res = client.post("/resources", json={
        "name": "Generic Helper",
        "capabilities": ["RESCUE"],
        "latitude": 10.027,
        "longitude": 76.308,
        "status": "AVAILABLE",
        # Notice: resource_type is omitted
    }).json()

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()

    rec_res = plan["response_option"]["resources"][0]
    assert rec_res["type"] == "Unknown"

    ev = plan["evidence"][0]
    type_fact = [f for f in ev["facts"] if "Resource type" in f]
    assert len(type_fact) == 1
    assert "Unknown" in type_fact[0]


def test_recommendations_preview_endpoint(client):
    """Verify GET /incidents/{incident_id}/recommendations returns the structured response."""
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"]
    )
    res = _register_resource(
        client, "Preview Res", ["RESCUE"],
        latitude=10.027, longitude=76.308, status="AVAILABLE", resource_type="Truck"
    )

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    preview = client.get(f"/incidents/{incident['id']}/recommendations")
    assert preview.status_code == 200, preview.text
    data = preview.json()

    assert data["incident_id"] == incident["id"]
    assert len(data["response_option"]["resources"]) == 1
    assert data["response_option"]["resources"][0]["resource_id"] == res["id"]
    assert data["constraints_considered"] == [
        "Required capability", "Resource availability", "Assignment status", "Location"
    ]
    assert "Preview Res" in data["rationale"]
    assert len(data["evidence"]) == 1
    assert data["evidence"][0]["resource_id"] == res["id"]
