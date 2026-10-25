import uuid

from app.database import SessionLocal
from app.models.incident import Incident, ResponsePlan, WorkflowAudit
from app.models.resources import Resource, ResourceAssignment, ResourceAvailabilityEvent


def _login(client, email, password, role):
    client.post("/auth/logout")
    return client.post("/auth/login", json={
        "email": email,
        "password": password,
        "role": role,
    })


def _create_recommended_plan(client, resource_count=1):
    assert _login(
        client, "admin@example.test", "test-admin-password-123", "ADMIN"
    ).status_code == 200
    department = client.post("/departments", json={
        "code": f"DEP-{uuid.uuid4().hex[:12].upper()}",
        "name": "Assignment test department",
        "department_type": "DISASTER_MANAGEMENT",
    })
    assert department.status_code == 201, department.text

    resources = []
    for index in range(resource_count):
        response = client.post("/resources", json={
            "code": f"RES-{uuid.uuid4().hex[:12].upper()}",
            "department_id": department.json()["id"],
            "resource_type": "RESCUE_TEAM",
            "name": f"Rescue team {index + 1}",
            "capabilities": ["RESCUE"],
            "latitude": 10.027,
            "longitude": 76.308,
            "availability": "AVAILABLE",
        })
        assert response.status_code == 201, response.text
        resources.append(response.json())

    assert _login(
        client, "user@example.test", "test-user-password-123", "USER"
    ).status_code == 200
    report = client.post("/reports", data={
        "disaster_type": "FLOOD",
        "description": "Flood water is rising; people are trapped and need rescue support.",
        "latitude": "10.027",
        "longitude": "76.308",
        "location_name": "Assignment test area",
    })
    assert report.status_code == 201, report.text

    assert _login(
        client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT"
    ).status_code == 200
    incident = client.post(f"/reports/{report.json()['id']}/confirm")
    assert incident.status_code == 201, incident.text
    plan = client.post(f"/incidents/{incident.json()['id']}/plans")
    assert plan.status_code == 201, plan.text
    assert {item["id"] for item in plan.json()["resource_candidates"]} == {
        item["id"] for item in resources
    }
    return incident.json(), plan.json(), resources


def test_resource_assignment_requires_approval_and_records_release(client):
    incident, plan, resources = _create_recommended_plan(client)
    resource_id = resources[0]["id"]
    path = f"/response-plans/{plan['id']}/assignments"

    not_approved = client.post(path, json={
        "resource_ids": [resource_id],
        "reason": "Coordinator assigns the nearest rescue team.",
    })
    assert not_approved.status_code == 409

    approved = client.post(
        f"/response-plans/{plan['id']}/approve",
        json={"reason": "Reviewed current incident evidence."},
    )
    assert approved.status_code == 200, approved.text
    assert client.patch(
        f"/resources/{resource_id}/availability",
        json={"availability": "ASSIGNED", "reason": "Bypass approved assignment."},
    ).status_code == 422

    invalid_resource = client.post(path, json={
        "resource_ids": [str(uuid.uuid4())],
        "reason": "This resource was not recommended.",
    })
    assert invalid_resource.status_code == 422

    assigned = client.post(path, json={
        "resource_ids": [resource_id],
        "reason": "Coordinator assigns the nearest rescue team.",
    })
    assert assigned.status_code == 200, assigned.text
    assignment = assigned.json()["assignments"][0]
    assert assignment["resource_id"] == resource_id
    assert assignment["incident_id"] == incident["id"]
    assert assignment["plan_id"] == plan["id"]
    assert assignment["is_active"] is True
    assert assigned.json()["status"] == "APPROVED"
    assert client.post(
        f"/incidents/{incident['id']}/close",
        json={"reason": "Close while a resource is still assigned."},
    ).status_code == 409

    with SessionLocal() as db:
        resource = db.get(Resource, uuid.UUID(resource_id))
        persisted_assignment = db.get(ResourceAssignment, uuid.UUID(assignment["id"]))
        events = db.query(ResourceAvailabilityEvent).filter_by(
            resource_id=uuid.UUID(resource_id),
        ).order_by(ResourceAvailabilityEvent.changed_at).all()
        audit = db.query(WorkflowAudit).filter_by(
            event_type="RESOURCES_ASSIGNED",
            plan_id=uuid.UUID(plan["id"]),
        ).one()
        assert resource.availability == "ASSIGNED"
        assert persisted_assignment.is_active
        assert [event.new_availability for event in events] == ["AVAILABLE", "ASSIGNED"]
        assert events[-1].changed_by == persisted_assignment.assigned_by
        assert audit.details["resource_ids"] == [resource_id]

    assert _login(
        client, "admin@example.test", "test-admin-password-123", "ADMIN"
    ).status_code == 200
    assert client.patch(
        f"/departments/{resources[0]['department_id']}",
        json={"is_active": False},
    ).status_code == 409
    assert client.patch(
        f"/resources/{resource_id}",
        json={"name": "Changed while assigned"},
    ).status_code == 409

    assert _login(
        client, "user@example.test", "test-user-password-123", "USER"
    ).status_code == 200
    assert client.post(
        f"/response-plans/{plan['id']}/assignments/{assignment['id']}/release",
        json={"reason": "Unauthorized release attempt."},
    ).status_code == 403
    assert _login(
        client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT"
    ).status_code == 200
    released = client.post(
        f"/response-plans/{plan['id']}/assignments/{assignment['id']}/release",
        json={"reason": "Rescue activity is complete."},
    )
    assert released.status_code == 200, released.text
    released_assignment = released.json()["assignments"][0]
    assert released_assignment["is_active"] is False
    assert released_assignment["release_reason"] == "Rescue activity is complete."
    closed = client.post(
        f"/incidents/{incident['id']}/close",
        json={"reason": "Response is complete after resource release."},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"
    assert client.post(
        f"/response-plans/{plan['id']}/approve",
        json={"reason": "Cannot approve a closed incident."},
    ).status_code == 409
    reopened = client.post(
        f"/incidents/{incident['id']}/reopen",
        json={"reason": "New hazard information was received."},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "ACTIVE"
    with SessionLocal() as db:
        assert db.get(Resource, uuid.UUID(resource_id)).availability == "AVAILABLE"
        assert db.get(ResourceAssignment, uuid.UUID(assignment["id"])).released_by

    repeated_release = client.post(
        f"/response-plans/{plan['id']}/assignments/{assignment['id']}/release",
        json={"reason": "Duplicate release attempt."},
    )
    assert repeated_release.status_code == 409


def test_assignment_rechecks_all_selected_resource_states_atomically(client):
    _, plan, resources = _create_recommended_plan(client, resource_count=2)
    approved = client.post(
        f"/response-plans/{plan['id']}/approve",
        json={"reason": "Coordinator approved the plan."},
    )
    assert approved.status_code == 200, approved.text

    changed_resource = resources[1]
    unavailable = client.patch(
        f"/resources/{changed_resource['id']}/availability",
        json={"availability": "UNAVAILABLE", "reason": "Unit is undergoing maintenance."},
    )
    assert unavailable.status_code == 200, unavailable.text

    rejected = client.post(
        f"/response-plans/{plan['id']}/assignments",
        json={
            "resource_ids": [resource["id"] for resource in resources],
            "reason": "Assign both recommended teams.",
        },
    )
    assert rejected.status_code == 409

    with SessionLocal() as db:
        assert db.get(Resource, uuid.UUID(resources[0]["id"])).availability == "AVAILABLE"
        assert db.get(Resource, uuid.UUID(resources[1]["id"])).availability == "UNAVAILABLE"
        assert db.query(ResourceAssignment).count() == 0


def test_coordinator_can_assign_available_nonrecommended_resource(client):
    incident, plan, recommended_resources = _create_recommended_plan(client)
    assert _login(
        client, "admin@example.test", "test-admin-password-123", "ADMIN"
    ).status_code == 200
    nonrecommended = client.post("/resources", json={
        "code": f"RES-{uuid.uuid4().hex[:12].upper()}",
        "department_id": recommended_resources[0]["department_id"],
        "resource_type": "VEHICLE",
        "name": "Coordinator-selected police unit",
        "capabilities": ["POLICE"],
        "latitude": 10.027,
        "longitude": 76.308,
        "availability": "AVAILABLE",
    })
    assert nonrecommended.status_code == 201, nonrecommended.text
    nonrecommended_id = nonrecommended.json()["id"]
    assert nonrecommended_id not in {
        candidate["id"] for candidate in plan["resource_candidates"]
    }

    assert _login(
        client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT"
    ).status_code == 200
    assert client.post(
        f"/response-plans/{plan['id']}/approve",
        json={"reason": "Coordinator approved the plan."},
    ).status_code == 200

    assigned = client.post(
        f"/response-plans/{plan['id']}/assignments",
        json={
            "resource_ids": [nonrecommended_id],
            "reason": "Coordinator selected an additional nearby unit.",
        },
    )
    assert assigned.status_code == 200, assigned.text
    assignment = next(
        item for item in assigned.json()["assignments"]
        if item["resource_id"] == nonrecommended_id
    )
    assert assignment["incident_id"] == incident["id"]
    assert assignment["is_active"] is True

    with SessionLocal() as db:
        audit = db.query(WorkflowAudit).filter_by(
            event_type="RESOURCES_ASSIGNED",
            plan_id=uuid.UUID(plan["id"]),
        ).one()
        assert audit.details["resource_ids"] == [nonrecommended_id]
        assert audit.details["recommended_resource_ids"] == []
        assert audit.details["coordinator_selected_nonrecommended_resource_ids"] == [
            nonrecommended_id,
        ]
        assert db.get(Resource, uuid.UUID(nonrecommended_id)).availability == "ASSIGNED"


def test_bulk_make_available_releases_assignments_and_records_history(client):
    _, plan, resources = _create_recommended_plan(client)
    resource_id = resources[0]["id"]
    assert client.post(
        f"/response-plans/{plan['id']}/approve",
        json={"reason": "Coordinator approved the plan."},
    ).status_code == 200
    assigned = client.post(
        f"/response-plans/{plan['id']}/assignments",
        json={"resource_ids": [resource_id], "reason": "Assign for response."},
    )
    assert assigned.status_code == 200, assigned.text
    assignment_id = assigned.json()["assignments"][0]["id"]

    assert _login(
        client, "admin@example.test", "test-admin-password-123", "ADMIN"
    ).status_code == 200
    department_id = resources[0]["department_id"]
    for status in ("UNAVAILABLE", "AVAILABLE"):
        registered = client.post("/resources", json={
            "code": f"RES-{uuid.uuid4().hex[:12].upper()}",
            "department_id": department_id,
            "resource_type": "RESCUE_TEAM",
            "name": f"Bulk reset {status.lower()}",
            "capabilities": ["RESCUE"],
            "latitude": 10.027,
            "longitude": 76.308,
            "availability": status,
        })
        assert registered.status_code == 201, registered.text

    assert _login(
        client, "user@example.test", "test-user-password-123", "USER"
    ).status_code == 200
    assert client.post(
        "/resources/availability/make-all-available",
        json={"reason": "Reset after the demo."},
    ).status_code == 403

    assert _login(
        client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT"
    ).status_code == 200
    response = client.post(
        "/resources/availability/make-all-available",
        json={"reason": "Reset after the demo."},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["resources_made_available"] == 2
    assert result["already_available_count"] == 1
    assert result["released_assignment_count"] == 1
    assert result["skipped"] == []

    with SessionLocal() as db:
        assignment = db.get(ResourceAssignment, uuid.UUID(assignment_id))
        assert assignment.is_active is False
        assert assignment.release_reason == "Reset after the demo."
        assert db.get(Resource, uuid.UUID(resource_id)).availability == "AVAILABLE"
        assert db.query(ResourceAvailabilityEvent).filter_by(
            resource_id=uuid.UUID(resource_id),
        ).order_by(ResourceAvailabilityEvent.changed_at).all()[-1].reason == "Reset after the demo."
        assert db.query(WorkflowAudit).filter_by(
            event_type="RESOURCE_ASSIGNMENT_RELEASED",
            plan_id=uuid.UUID(plan["id"]),
        ).count() == 1
        bulk_audit = db.query(WorkflowAudit).filter_by(
            event_type="RESOURCES_MADE_AVAILABLE",
        ).one()
        assert bulk_audit.details["released_assignment_ids"] == [assignment_id]


def test_deleting_report_removes_its_workflow_and_releases_active_resources(client):
    incident, plan, resources = _create_recommended_plan(client)
    resource_id = resources[0]["id"]
    report_id = incident["report_id"]
    assert _login(
        client, "user@example.test", "test-user-password-123", "USER"
    ).status_code == 200
    linked_report = client.post("/reports", data={
        "disaster_type": "FLOOD",
        "description": "A second caller reports the same flood.",
        "latitude": "10.027",
        "longitude": "76.308",
        "location_name": "Assignment test area",
    })
    assert linked_report.status_code == 201, linked_report.text
    assert _login(
        client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT"
    ).status_code == 200
    assert client.post(
        f"/incidents/{incident['id']}/reports/{linked_report.json()['id']}/link",
        json={"reason": "The reports describe the same flood."},
    ).status_code == 200
    assert client.post(
        f"/response-plans/{plan['id']}/approve",
        json={"reason": "Coordinator approved the plan."},
    ).status_code == 200
    assignment = client.post(
        f"/response-plans/{plan['id']}/assignments",
        json={"resource_ids": [resource_id], "reason": "Assign for response."},
    )
    assert assignment.status_code == 200, assignment.text

    response = client.request(
        "DELETE",
        f"/reports/{report_id}",
        json={"reason": "Duplicate test report."},
    )
    assert response.status_code == 204, response.text
    assert client.get(f"/reports/{report_id}").status_code == 404
    assert client.get("/incidents").json() == []
    returned_to_queue = client.get(f"/reports/{linked_report.json()['id']}")
    assert returned_to_queue.status_code == 200
    assert returned_to_queue.json()["status"] == "SUBMITTED"
    assert returned_to_queue.json()["incident_links"] == []

    with SessionLocal() as db:
        assert db.get(Resource, uuid.UUID(resource_id)).availability == "AVAILABLE"
        assert db.query(ResourceAssignment).count() == 0
        assert db.query(ResponsePlan).count() == 0
        assert db.query(Incident).count() == 0
        release_event = db.query(ResourceAvailabilityEvent).filter_by(
            resource_id=uuid.UUID(resource_id),
            new_availability="AVAILABLE",
        ).order_by(ResourceAvailabilityEvent.changed_at.desc()).first()
        assert release_event.reason == "Duplicate test report."
        deletion_event = db.query(WorkflowAudit).filter_by(
            event_type="REPORT_DELETED",
        ).one()
        assert deletion_event.details["report_id"] == report_id
