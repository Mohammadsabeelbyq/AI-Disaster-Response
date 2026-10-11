import math

import pytest


def _login(client, email, password, role):
    client.post("/auth/logout")
    return client.post("/auth/login", json={
        "email": email,
        "password": password,
        "role": role,
    })


def _confirmed_incident(client, latitude=0, longitude=0):
    report = client.post("/reports", data={
        "disaster_type": "FLOOD",
        "description": "Flooding near the river",
        "latitude": str(latitude),
        "longitude": str(longitude),
    }).json()
    assert _login(
        client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT"
    ).status_code == 200
    assert client.post(f"/reports/{report['id']}/review").status_code == 200
    incident = client.post(f"/reports/{report['id']}/confirm")
    assert incident.status_code == 201, incident.text
    return incident.json(), report


def test_impact_area_can_be_created_retrieved_and_updated_for_its_incident(client):
    incident, _ = _confirmed_incident(client)
    payload = {"geometry_type": "RADIUS", "radius_m": 1250}

    saved = client.put(f"/incidents/{incident['id']}/impact-area", json=payload)
    assert saved.status_code == 200, saved.text
    assert saved.json()["incident_id"] == incident["id"]
    assert saved.json()["radius_m"] == 1250
    assert saved.json()["polygon"] is None

    fetched = client.get(f"/incidents/{incident['id']}/impact-area")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == saved.json()["id"]

    updated = client.put(f"/incidents/{incident['id']}/impact-area", json={
        "geometry_type": "POLYGON",
        "polygon": {"type": "Polygon", "coordinates": [[
            [76.29, 10.02], [76.31, 10.02], [76.31, 10.04],
            [76.29, 10.02],
        ]]},
    })
    assert updated.status_code == 200, updated.text
    assert updated.json()["id"] == saved.json()["id"]
    assert updated.json()["geometry_type"] == "POLYGON"
    assert updated.json()["polygon"]["type"] == "Polygon"

    other, _ = _confirmed_incident(client, latitude=1, longitude=1)
    assert client.get(f"/incidents/{other['id']}/impact-area").json() is None


@pytest.mark.parametrize("payload", [
    {"geometry_type": "RADIUS", "radius_m": 0},
    {"geometry_type": "RADIUS", "radius_m": 100001},
    {"geometry_type": "RADIUS", "radius_m": 100, "polygon": {
        "type": "Polygon", "coordinates": [[[0, 0], [1, 0], [0, 1], [0, 0]]],
    }},
    {"geometry_type": "POLYGON", "polygon": {
        "type": "Polygon", "coordinates": [[[181, 0], [0, 1], [1, 0], [181, 0]]],
    }},
    {"geometry_type": "POLYGON", "polygon": {
        "type": "Polygon", "coordinates": [[[0, 91], [1, 0], [0, 1], [0, 91]]],
    }},
    {"geometry_type": "POLYGON", "polygon": {
        "type": "Polygon", "coordinates": [[[0, 0], [1, 1], [2, 2], [0, 0]]],
    }},
    {"geometry_type": "POLYGON", "polygon": {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]]],
    }},
    {"geometry_type": "POLYGON", "polygon": {
        "type": "Polygon",
        "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2]]],
    }},
])
def test_impact_area_rejects_invalid_radius_coordinates_and_geometry(client, payload):
    incident, _ = _confirmed_incident(client)
    response = client.put(f"/incidents/{incident['id']}/impact-area", json=payload)
    assert response.status_code == 422


def test_impact_area_requires_coordinator_authorization(client):
    incident, _ = _confirmed_incident(client)
    _login(client, "user@example.test", "test-user-password-123", "USER")
    assert client.get(f"/incidents/{incident['id']}/impact-area").status_code == 403
    assert client.put(f"/incidents/{incident['id']}/impact-area", json={
        "geometry_type": "RADIUS", "radius_m": 100,
    }).status_code == 403
    client.post("/auth/logout")
    assert client.get(f"/incidents/{incident['id']}/impact-area").status_code == 401


def test_nearby_resources_are_distance_ranked_and_filtered_by_capability_and_status(client):
    incident, _ = _confirmed_incident(client)
    assert client.post("/resources", json={"name": "Not an administrator"}).status_code == 403
    assert _login(
        client, "admin@example.test", "test-admin-password-123", "ADMIN"
    ).status_code == 200

    near = client.post("/resources", json={
        "name": "Local Rescue",
        "latitude": 0,
        "longitude": 0.01,
        "capabilities": ["RESCUE", "water rescue", "RESCUE"],
        "status": "AVAILABLE",
    })
    farther = client.post("/resources", json={
        "name": "Regional Rescue",
        "latitude": 0,
        "longitude": 0.02,
        "capabilities": ["RESCUE"],
        "status": "AVAILABLE",
    })
    wrong_capability = client.post("/resources", json={
        "name": "Medical Unit",
        "latitude": 0,
        "longitude": 0.005,
        "capabilities": ["MEDICAL"],
        "status": "AVAILABLE",
    })
    busy = client.post("/resources", json={
        "name": "Busy Rescue",
        "latitude": 0,
        "longitude": 0.003,
        "capabilities": ["RESCUE"],
        "status": "BUSY",
    })
    missing_location = client.post("/resources", json={
        "name": "Unlocated Rescue",
        "capabilities": ["RESCUE"],
    })
    assert all(response.status_code == 201 for response in
               [near, farther, wrong_capability, busy, missing_location])
    assert near.json()["capabilities"] == ["RESCUE", "WATER_RESCUE"]

    _login(client, "user@example.test", "test-user-password-123", "USER")
    assert client.get(f"/incidents/{incident['id']}/resources").status_code == 403
    _login(client, "coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT")
    result = client.get(f"/incidents/{incident['id']}/resources")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["incident_id"] == incident["id"]
    assert body["requested_capabilities"] == ["RESCUE", "WATER_RESCUE"]
    assert [resource["id"] for resource in body["resources"]] == [
        near.json()["id"], farther.json()["id"],
    ]
    assert body["resources"][0]["distance_m"] == round(
        2 * 6_371_008.8 * math.asin(math.sin(math.radians(0.01) / 2)))
    assert body["resources"][0]["status"] == "AVAILABLE"
    assert body["resources"][0]["capabilities"] == ["RESCUE", "WATER_RESCUE"]

    include_busy = client.get(
        f"/incidents/{incident['id']}/resources?status=AVAILABLE&status=BUSY")
    assert include_busy.status_code == 200
    assert busy.json()["id"] in {
        resource["id"] for resource in include_busy.json()["resources"]
    }
    capability_filter = client.get(
        f"/incidents/{incident['id']}/resources?capability=MEDICAL")
    assert capability_filter.status_code == 200
    assert [resource["id"] for resource in capability_filter.json()["resources"]] == [
        wrong_capability.json()["id"],
    ]
    assert client.get(
        f"/incidents/{incident['id']}/resources?radius_m=100001").status_code == 422


def test_nearby_resources_empty_results_bad_ids_and_registration_validation(client):
    incident, _ = _confirmed_incident(client)
    empty = client.get(f"/incidents/{incident['id']}/resources")
    assert empty.status_code == 200
    assert empty.json()["resources"] == []

    invalid_id = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/incidents/{invalid_id}/resources").status_code == 404
    assert client.get(f"/incidents/{invalid_id}/impact-area").status_code == 404

    assert _login(client, "admin@example.test", "test-admin-password-123", "ADMIN").status_code == 200
    assert client.post("/resources", json={
        "name": "Invalid partial location",
        "latitude": 0,
    }).status_code == 422
