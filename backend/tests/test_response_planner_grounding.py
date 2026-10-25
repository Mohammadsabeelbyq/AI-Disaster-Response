"""Unit and integration tests for FR-28 (Planner Grounding) and FR-29 (Rationale & Evidence)."""
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from app.database import SessionLocal
from app.models.incident import ResponsePlan
from app.models.resources import Resource
from app.services import incident_service
from app.services.groq_planner import GroqPlanDraft, GroqPlannerError


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
                       status="AVAILABLE", resource_type="RESCUE_TEAM"):
    _login(client, "admin@example.test", "test-admin-password-123", "ADMIN")
    department = client.post("/departments", json={
        "code": f"DEP-{uuid.uuid4().hex[:12].upper()}",
        "name": f"{name} Department",
        "department_type": "DISASTER_MANAGEMENT",
    })
    assert department.status_code == 201, department.text
    payload = {
        "code": f"RES-{uuid.uuid4().hex[:12].upper()}",
        "department_id": department.json()["id"],
        "name": name,
        "capabilities": capabilities,
        "availability": status,
        "resource_type": resource_type,
        "latitude": latitude,
        "longitude": longitude,
    }
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
        latitude=10.030, longitude=76.310, status="AVAILABLE", resource_type="VEHICLE"
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
    assert rec_resources[0]["type"] == "VEHICLE"
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
        latitude=10.028, longitude=76.309, status="UNAVAILABLE", resource_type="VEHICLE"
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

    _register_resource(
        client, "Assigned Squad", ["RESCUE"], latitude=10.028, longitude=76.309,
        status="ASSIGNED")

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()
    assert plan["response_option"]["resources"] == []
    assert plan["resource_candidates"] == []


def test_pending_plan_recommendation_does_not_mark_resource_as_assigned(client):
    """Draft recommendations do not reserve resources before an assignment exists."""
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
    plan1 = client.post(f"/incidents/{inc1['id']}/plans").json()
    assert plan1["response_option"]["resources"][0]["resource_id"] == shared_res["id"]

    plan2 = client.post(f"/incidents/{inc2['id']}/plans").json()
    assert plan2["response_option"]["resources"][0]["resource_id"] == shared_res["id"]


def test_unlocated_resource_is_rejected_at_registration(client):
    _login(client, "admin@example.test", "test-admin-password-123", "ADMIN")
    department = client.post("/departments", json={
        "code": f"DEP-{uuid.uuid4().hex[:12].upper()}",
        "name": "Location validation department",
        "department_type": "DISASTER_MANAGEMENT",
    }).json()
    response = client.post("/resources", json={
        "code": f"RES-{uuid.uuid4().hex[:12].upper()}",
        "department_id": department["id"],
        "resource_type": "RESCUE_TEAM",
        "name": "Unlocated Unit",
        "capabilities": ["RESCUE"],
        "latitude": None,
        "longitude": None,
    })
    assert response.status_code == 422


def test_missing_resource_type_is_rejected_at_registration(client):
    _login(client, "admin@example.test", "test-admin-password-123", "ADMIN")
    department = client.post("/departments", json={
        "code": f"DEP-{uuid.uuid4().hex[:12].upper()}",
        "name": "Type validation department",
        "department_type": "DISASTER_MANAGEMENT",
    }).json()
    response = client.post("/resources", json={
        "code": f"RES-{uuid.uuid4().hex[:12].upper()}",
        "department_id": department["id"],
        "name": "Untyped unit",
        "capabilities": ["RESCUE"],
        "latitude": 10.027,
        "longitude": 76.308,
    })
    assert response.status_code == 422


def test_resources_with_incompatible_capabilities_are_excluded(client):
    """FR-28: Resources that do not meet incident capability requirements are excluded."""
    incident = _create_confirmed_incident(
        client, disaster_type="FIRE", requested_assistance=["FIRE_SUPPRESSION"]
    )
    # Register medical-only resource
    _register_resource(
        client, "Ambulance 101", ["MEDICAL", "MEDICAL_AID"],
        latitude=10.027, longitude=76.308, status="AVAILABLE", resource_type="VEHICLE"
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


def test_operational_resource_radius_is_capped_at_100_km(client):
    incident = _create_confirmed_incident(
        client, disaster_type="FIRE", requested_assistance=["RESCUE"],
        latitude=10.0, longitude=76.0,
    )
    within_radius = _register_resource(
        client, "Rescue within operational radius", ["RESCUE"],
        latitude=10.8, longitude=76.0,
    )
    beyond_radius = _register_resource(
        client, "Rescue beyond operational radius", ["RESCUE"],
        latitude=11.0, longitude=76.0,
    )

    nearby = client.get(f"/incidents/{incident['id']}/resources")
    assert nearby.status_code == 200, nearby.text
    assert nearby.json()["radius_m"] == 100000
    nearby_ids = {item["id"] for item in nearby.json()["resources"]}
    assert within_radius["id"] in nearby_ids
    assert beyond_radius["id"] not in nearby_ids

    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201, response.text
    plan = response.json()

    candidate_ids = {item["resource_id"] for item in plan["resource_candidates"]}
    assert within_radius["id"] in candidate_ids
    assert beyond_radius["id"] not in candidate_ids


def test_smaller_incident_radius_still_narrows_100_km_operational_radius(client):
    incident = _create_confirmed_incident(
        client, disaster_type="FIRE", requested_assistance=["RESCUE"],
        latitude=10.0, longitude=76.0,
    )
    assert client.put(f"/incidents/{incident['id']}/impact-area", json={
        "geometry_type": "RADIUS", "radius_m": 50000,
    }).status_code == 200
    close_rescue = _register_resource(
        client, "Rescue within incident radius", ["RESCUE"],
        latitude=10.3, longitude=76.0,
    )
    outside_incident_area = _register_resource(
        client, "Rescue outside incident radius", ["RESCUE"],
        latitude=10.55, longitude=76.0,
    )

    nearby = client.get(f"/incidents/{incident['id']}/resources")
    assert nearby.status_code == 200, nearby.text
    assert nearby.json()["radius_m"] == 50000
    nearby_ids = {item["id"] for item in nearby.json()["resources"]}
    assert close_rescue["id"] in nearby_ids
    assert outside_incident_area["id"] not in nearby_ids


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
                r = sub_db.get(Resource, res_id)
                r.availability = "UNAVAILABLE"
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
        latitude=10.028, longitude=76.309, status="AVAILABLE", resource_type="VEHICLE"
    )

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    response = client.post(f"/incidents/{incident['id']}/plans")
    assert response.status_code == 201
    plan = response.json()

    # Rationale explains why the resource was selected
    assert "Coastal Guard 1" in plan["rationale"]
    assert "VEHICLE" in plan["rationale"]
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
    assert "VEHICLE" in facts_str
    assert "coordinates" in facts_str
    assert "metres" in facts_str


def test_missing_resource_type_is_rejected(client):
    """A resource cannot enter planning without required category data."""
    _login(client, "admin@example.test", "test-admin-password-123", "ADMIN")
    department = client.post("/departments", json={
        "code": f"DEP-{uuid.uuid4().hex[:12].upper()}",
        "name": "Missing type test department",
        "department_type": "DISASTER_MANAGEMENT",
    }).json()
    response = client.post("/resources", json={
        "code": f"RES-{uuid.uuid4().hex[:12].upper()}",
        "department_id": department["id"],
        "name": "Generic Helper",
        "capabilities": ["RESCUE"],
        "latitude": 10.027,
        "longitude": 76.308,
    })
    assert response.status_code == 422


def test_recommendations_preview_endpoint(client):
    """Verify GET /incidents/{incident_id}/recommendations returns the structured response."""
    incident = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"]
    )
    res = _register_resource(
        client, "Preview Res", ["RESCUE"],
        latitude=10.027, longitude=76.308, status="AVAILABLE", resource_type="VEHICLE"
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


def _groq_test_settings():
    return SimpleNamespace(
        groq_api_key="test-key-not-a-real-secret",
        groq_model="test-groq-model",
        groq_timeout_seconds=1,
        groq_max_resources=10,
        groq_max_tokens=100,
        groq_temperature=0,
        resource_search_radius_metres=50000,
        resource_max_search_radius_metres=100000,
    )


def test_groq_planner_receives_region_and_eligible_database_resources(client):
    incident_data = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"],
        latitude=10.0, longitude=76.0,
    )
    resource = _register_resource(
        client, "Regional rescue unit", ["RESCUE"],
        latitude=10.001, longitude=76.001,
    )
    draft = GroqPlanDraft(
        recommended_actions=["Coordinator verifies the reported access route."],
        resource_ids=[resource["id"]],
        rationale="The registered rescue unit is nearby and available.",
        constraints_considered=["Capability", "Availability", "Distance"],
    )

    with patch("app.services.incident_service.get_settings", return_value=_groq_test_settings()), \
         patch("app.services.incident_service.generate_plan_draft", return_value=draft) as planner:
        with SessionLocal() as db:
            incident = incident_service.get_incident(db, uuid.UUID(incident_data["id"]))
            plan = incident_service.generate_response_plan(db, incident.id, incident.confirmed_by)

    snapshot = planner.call_args.args[0]
    assert snapshot["incident"]["description"] == (
        f"Incident requiring assistance at {incident_data['report']['latitude']}, "
        f"{incident_data['report']['longitude']}"
    )
    assert snapshot["region"]["latitude"] == 10.0
    assert snapshot["region"]["longitude"] == 76.0
    assert [row["id"] for row in snapshot["eligible_resources"]] == [resource["id"]]
    assert snapshot["eligible_resources"][0]["availability"] == "AVAILABLE"
    assert plan.planner_provider == "GROQ"
    assert plan.planner_model == "test-groq-model"
    assert plan.recommended_actions == draft.recommended_actions
    assert [candidate["id"] for candidate in plan.resource_candidates] == [resource["id"]]


def test_groq_planner_receives_structured_context_from_linked_reports(client):
    incident_data = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"],
        latitude=10.0, longitude=76.0,
    )
    _login(client, "user@example.test", "test-user-password-123", "USER")
    linked_report = client.post("/reports", data={
        "disaster_type": "FLOOD",
        "description": "Several families need clean drinking water.",
        "latitude": "10.002",
        "longitude": "76.003",
        "location_name": "Nearby area",
    }).json()

    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    linked_facts = {
        **linked_report["extraction"]["extracted_facts"],
        "requested_assistance": ["WATER", "MEDICAL"],
    }
    corrected = client.patch(
        f"/reports/{linked_report['id']}/extraction",
        json={"facts": linked_facts},
    )
    assert corrected.status_code == 200, corrected.text
    linked = client.post(
        f"/incidents/{incident_data['id']}/reports/{linked_report['id']}/link",
        json={"reason": "Reports describe the same flood event."},
    )
    assert linked.status_code == 200, linked.text

    draft = GroqPlanDraft(
        recommended_actions=["Coordinator checks access and water needs."],
        resource_ids=[],
        rationale="The linked report adds nearby water and medical needs.",
    )
    with patch("app.services.incident_service.get_settings", return_value=_groq_test_settings()), \
         patch("app.services.incident_service.generate_plan_draft", return_value=draft) as planner:
        with SessionLocal() as db:
            incident = incident_service.get_incident(db, uuid.UUID(incident_data["id"]))
            incident_service.generate_response_plan(db, incident.id, incident.confirmed_by)

    linked_context = planner.call_args.args[0]["linked_reports"]
    assert len(linked_context) == 1
    assert linked_context[0]["report_id"] == linked_report["id"]
    assert linked_context[0]["description"] == "Several families need clean drinking water."
    assert linked_context[0]["effective_facts"]["requested_assistance"] == ["WATER", "MEDICAL"]
    assert linked_context[0]["location"] == {
        "latitude": 10.002,
        "longitude": 76.003,
        "location_name": "Nearby area",
    }


def test_groq_cannot_add_unregistered_resource_ids(client):
    incident_data = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"])
    resource = _register_resource(client, "Known rescue unit", ["RESCUE"])
    invalid_draft = GroqPlanDraft(
        recommended_actions=["Verify the incident location."],
        resource_ids=[str(uuid.uuid4())],
        rationale="A made-up resource is recommended.",
    )

    with patch("app.services.incident_service.get_settings", return_value=_groq_test_settings()), \
         patch("app.services.incident_service.generate_plan_draft", return_value=invalid_draft):
        with SessionLocal() as db:
            incident = incident_service.get_incident(db, uuid.UUID(incident_data["id"]))
            plan = incident_service.generate_response_plan(db, incident.id, incident.confirmed_by)

    assert plan.planner_provider == "DETERMINISTIC"
    assert plan.planner_model is None
    assert [candidate["id"] for candidate in plan.resource_candidates] == [resource["id"]]


def test_groq_resource_is_rechecked_after_provider_response(client):
    incident_data = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"])
    resource = _register_resource(client, "Changing rescue unit", ["RESCUE"])
    draft = GroqPlanDraft(
        recommended_actions=["Use the available rescue team."],
        resource_ids=[resource["id"]],
        rationale="The rescue team is available.",
    )

    def change_availability_during_call(*_args, **_kwargs):
        with SessionLocal() as db:
            db.get(Resource, uuid.UUID(resource["id"])).availability = "UNAVAILABLE"
            db.commit()
        return draft

    with patch("app.services.incident_service.get_settings", return_value=_groq_test_settings()), \
         patch("app.services.incident_service.generate_plan_draft", side_effect=change_availability_during_call):
        with SessionLocal() as db:
            incident = incident_service.get_incident(db, uuid.UUID(incident_data["id"]))
            plan = incident_service.generate_response_plan(db, incident.id, incident.confirmed_by)

    assert plan.planner_provider == "DETERMINISTIC"
    assert plan.planner_model is None
    assert plan.resource_candidates == []


def test_groq_provider_failure_uses_deterministic_database_plan(client):
    incident_data = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"])
    resource = _register_resource(client, "Fallback rescue unit", ["RESCUE"])

    with patch("app.services.incident_service.get_settings", return_value=_groq_test_settings()), \
         patch("app.services.incident_service.generate_plan_draft",
               side_effect=GroqPlannerError("provider unavailable")):
        with SessionLocal() as db:
            incident = incident_service.get_incident(db, uuid.UUID(incident_data["id"]))
            plan = incident_service.generate_response_plan(db, incident.id, incident.confirmed_by)

    assert plan.planner_provider == "DETERMINISTIC"
    assert plan.planner_model is None
    assert [candidate["id"] for candidate in plan.resource_candidates] == [resource["id"]]


def test_groq_provider_is_retried_once_before_deterministic_fallback(client):
    incident_data = _create_confirmed_incident(
        client, disaster_type="FLOOD", requested_assistance=["RESCUE"])
    resource = _register_resource(client, "Retried rescue unit", ["RESCUE"])
    draft = GroqPlanDraft(
        recommended_actions=["Coordinate with the nearby rescue team."],
        resource_ids=[resource["id"]],
        rationale="The eligible rescue unit is nearby.",
    )

    with patch("app.services.incident_service.get_settings", return_value=_groq_test_settings()), \
         patch("app.services.incident_service.generate_plan_draft",
               side_effect=[GroqPlannerError("temporary provider failure"), draft]) as planner:
        with SessionLocal() as db:
            incident = incident_service.get_incident(db, uuid.UUID(incident_data["id"]))
            plan = incident_service.generate_response_plan(db, incident.id, incident.confirmed_by)

    assert planner.call_count == 2
    assert plan.planner_provider == "GROQ"
    assert plan.planner_model == "test-groq-model"
    assert plan.recommended_actions == draft.recommended_actions
