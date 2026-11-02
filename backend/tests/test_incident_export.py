"""Tests for ADM-44: Incident Data Export."""
import csv
import io
import json


def _login_coordinator(client):
    client.post("/auth/logout")
    return client.post("/auth/login", json={
        "email": "coordinator@example.test",
        "password": "test-coordinator-password-123",
        "role": "MANAGEMENT",
    })


def _login_user(client):
    client.post("/auth/logout")
    return client.post("/auth/login", json={
        "email": "user@example.test",
        "password": "test-user-password-123",
        "role": "USER",
    })


def test_export_csv_and_json(client, valid_form):
    _login_coordinator(client)
    # Create two incidents
    sub1 = client.post("/reports", data=valid_form).json()
    inc1 = client.post(f"/reports/{sub1['id']}/confirm").json()

    sub2 = client.post("/reports", data={
        "disaster_type": "FIRE",
        "description": "Industrial fire outbreak in warehouse",
        "latitude": "10.05",
        "longitude": "76.32",
        "location_name": "Kalamassery",
    }).json()
    inc2 = client.post(f"/reports/{sub2['id']}/confirm").json()

    # 1. Export CSV
    csv_res = client.get("/incidents/export?format=csv")
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers["content-type"]
    assert "attachment; filename=\"incidents_export_" in csv_res.headers["content-disposition"]
    assert csv_res.headers["content-disposition"].endswith(".csv\"")

    reader = csv.DictReader(io.StringIO(csv_res.text))
    rows = list(reader)
    assert len(rows) >= 2
    row_ids = [r["incident_id"] for r in rows]
    assert inc1["id"] in row_ids
    assert inc2["id"] in row_ids
    # Check fields exist
    assert "disaster_type" in rows[0]
    assert "status" in rows[0]
    assert "location_name" in rows[0]
    assert "priority_band" in rows[0]

    # 2. Export JSON
    json_res = client.get("/incidents/export?format=json")
    assert json_res.status_code == 200
    assert "application/json" in json_res.headers["content-type"]
    assert "attachment; filename=\"incidents_export_" in json_res.headers["content-disposition"]
    assert json_res.headers["content-disposition"].endswith(".json\"")

    records = json_res.json()
    assert isinstance(records, list)
    assert len(records) >= 2
    json_ids = [r["incident_id"] for r in records]
    assert inc1["id"] in json_ids
    assert inc2["id"] in json_ids


def test_export_filters(client, valid_form):
    _login_coordinator(client)
    # Incident 1: FLOOD, Edappally
    sub1 = client.post("/reports", data=valid_form).json()
    inc1 = client.post(f"/reports/{sub1['id']}/confirm").json()

    # Incident 2: FIRE, Kalamassery
    sub2 = client.post("/reports", data={
        "disaster_type": "FIRE",
        "description": "Factory chemical fire",
        "latitude": "10.05",
        "longitude": "76.32",
        "location_name": "Kalamassery",
    }).json()
    inc2 = client.post(f"/reports/{sub2['id']}/confirm").json()

    # Filter by disaster_type=FIRE
    res = client.get("/incidents/export?format=json&disaster_type=FIRE")
    assert res.status_code == 200
    records = res.json()
    assert all(r["disaster_type"] == "FIRE" for r in records)
    ids = [r["incident_id"] for r in records]
    assert inc2["id"] in ids
    assert inc1["id"] not in ids

    # Filter by search=Kalamassery
    search_res = client.get("/incidents/export?format=json&search=Kalamassery")
    assert search_res.status_code == 200
    s_records = search_res.json()
    assert all("kalamassery" in (r["location_name"] or "").lower() or "kalamassery" in r["description"].lower() for r in s_records)


def test_export_empty_results_and_unsupported_format(client):
    _login_coordinator(client)
    # Empty filter
    res = client.get("/incidents/export?format=json&disaster_type=CYCLONE&search=nonexistentplace123")
    assert res.status_code == 200
    assert res.json() == []

    csv_res = client.get("/incidents/export?format=csv&disaster_type=CYCLONE&search=nonexistentplace123")
    assert csv_res.status_code == 200
    reader = csv.DictReader(io.StringIO(csv_res.text))
    assert list(reader) == []

    # Unsupported format
    bad_fmt = client.get("/incidents/export?format=xml")
    assert bad_fmt.status_code == 400
    assert "Unsupported export format" in bad_fmt.json()["detail"]


def test_export_authorization_and_sanitization(client, valid_form):
    _login_coordinator(client)
    sub = client.post("/reports", data=valid_form).json()
    client.post(f"/reports/{sub['id']}/confirm")

    # Regular user is forbidden
    _login_user(client)
    forbidden_res = client.get("/incidents/export?format=csv")
    assert forbidden_res.status_code == 403

    # Coordinator can export; verify no sensitive tokens / passwords in dump
    _login_coordinator(client)
    export_res = client.get("/incidents/export?format=json")
    content = export_res.text.lower()
    assert "password" not in content
    assert "secret" not in content
    assert "hash" not in content
