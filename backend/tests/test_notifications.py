"""Tests for ADM-42: Incident Alerts & Approval Notifications."""
import uuid
from unittest.mock import patch

from app.database import SessionLocal
from app.models.incident import Incident
from app.models.notification import Notification
from app.services import notification_service


def _login_coordinator(client):
    client.post("/auth/logout")
    return client.post("/auth/login", json={
        "email": "coordinator@example.test",
        "password": "test-coordinator-password-123",
        "role": "MANAGEMENT",
    })


def _login_admin(client):
    client.post("/auth/logout")
    return client.post("/auth/login", json={
        "email": "admin@example.test",
        "password": "test-admin-password-123",
        "role": "ADMIN",
    })


def _login_user(client):
    client.post("/auth/logout")
    return client.post("/auth/login", json={
        "email": "user@example.test",
        "password": "test-user-password-123",
        "role": "USER",
    })


def test_notifications_lifecycle_and_api(client, valid_form):
    # 1. User submits a report
    _login_user(client)
    submitted = client.post("/reports", data=valid_form).json()
    report_id = submitted["id"]

    # Coordinator logs in and checks notifications
    _login_coordinator(client)
    res = client.get("/notifications")
    assert res.status_code == 200
    notifs = res.json()
    assert any(n["notification_type"] == "NEW_REPORT" for n in notifs)

    # 2. Coordinator confirms report into incident -> NEW_INCIDENT notification
    confirmed = client.post(f"/reports/{report_id}/confirm")
    assert confirmed.status_code == 201
    incident_id = confirmed.json()["id"]

    notifs = client.get("/notifications").json()
    assert any(
        n["notification_type"] == "NEW_INCIDENT" and n["incident_id"] == incident_id
        for n in notifs
    )

    # 3. Priority override -> INCIDENT_PRIORITY_CHANGED notification
    override_res = client.post(
        f"/incidents/{incident_id}/priority/override",
        json={"band": "CRITICAL", "reason": "Severe escalation"},
    )
    assert override_res.status_code == 200
    notifs = client.get("/notifications").json()
    priority_notifs = [n for n in notifs if n["notification_type"] == "INCIDENT_PRIORITY_CHANGED"]
    assert len(priority_notifs) >= 1
    assert "CRITICAL" in priority_notifs[0]["title"]

    # 4. Generate response plan -> PLAN_AWAITING_APPROVAL notification
    plan_res = client.post(f"/incidents/{incident_id}/plans")
    assert plan_res.status_code == 201
    plan_id = plan_res.json()["id"]

    notifs = client.get("/notifications").json()
    assert any(
        n["notification_type"] == "PLAN_AWAITING_APPROVAL" and n["response_plan_id"] == plan_id
        for n in notifs
    )

    # 5. Decide plan (Approve) -> PLAN_APPROVED notification
    decide_res = client.post(
        f"/response-plans/{plan_id}/approve",
        json={"reason": "Tactical review approved."},
    )
    assert decide_res.status_code == 200

    notifs = client.get("/notifications").json()
    assert any(
        n["notification_type"] == "PLAN_APPROVED" and n["response_plan_id"] == plan_id
        for n in notifs
    )

    # 6. Check unread count
    count_res = client.get("/notifications/unread-count")
    assert count_res.status_code == 200
    unread_count = count_res.json()["unread_count"]
    assert unread_count >= 4

    # 7. Mark single notification as read
    first_notif_id = notifs[0]["id"]
    read_res = client.patch(f"/notifications/{first_notif_id}/read")
    assert read_res.status_code == 200
    assert read_res.json()["is_read"] is True

    new_count = client.get("/notifications/unread-count").json()["unread_count"]
    assert new_count == unread_count - 1

    # 8. Mark all as read
    read_all_res = client.patch("/notifications/read-all")
    assert read_all_res.status_code == 200
    assert read_all_res.json()["updated_count"] == new_count

    zero_count = client.get("/notifications/unread-count").json()["unread_count"]
    assert zero_count == 0


def test_operation_failure_generates_coordinator_notification(client, valid_form):
    _login_coordinator(client)
    submitted = client.post("/reports", data=valid_form).json()
    incident_res = client.post(f"/reports/{submitted['id']}/confirm").json()
    plan_res = client.post(f"/incidents/{incident_res['id']}/plans").json()
    plan_id = plan_res["id"]

    # First approve plan
    client.post(f"/response-plans/{plan_id}/approve", json={"reason": "Approved initially"})

    # Attempt to approve again should fail (409 Conflict) and trigger OPERATION_FAILED notification
    fail_res = client.post(f"/response-plans/{plan_id}/approve", json={"reason": "Duplicate attempt"})
    assert fail_res.status_code == 409

    notifs = client.get("/notifications").json()
    assert any(
        n["notification_type"] == "OPERATION_FAILED" and "Plan Decision" in n["title"]
        for n in notifs
    )


def test_user_cannot_access_other_users_private_notifications(client):
    _login_coordinator(client)
    coord_notifs = client.get("/notifications").json()

    _login_user(client)
    user_notifs = client.get("/notifications").json()

    # User cannot mark coordinator's notification as read
    if coord_notifs:
        target_id = coord_notifs[0]["id"]
        tamper_res = client.patch(f"/notifications/{target_id}/read")
        assert tamper_res.status_code == 404


def test_duplicate_events_prevent_duplicate_notifications(client):
    _login_coordinator(client)
    with SessionLocal() as db:
        coordinators = notification_service.get_authorized_coordinators(db)
        assert len(coordinators) > 0
        target_user = coordinators[0]

        # First dispatch
        n1 = notification_service.create_notification(
            db,
            recipient_id=target_user.id,
            notification_type="TEST_EVENT",
            title="Deduplication Test",
            message="Test message",
            dedupe_key="test_dedupe_123",
        )
        db.commit()
        assert n1 is not None

        # Second dispatch with identical dedupe key
        n2 = notification_service.create_notification(
            db,
            recipient_id=target_user.id,
            notification_type="TEST_EVENT",
            title="Deduplication Test",
            message="Test message",
            dedupe_key="test_dedupe_123",
        )
        db.commit()
        # Should return existing and not insert a duplicate
        assert n2.id == n1.id


def test_notification_failure_does_not_break_incident_workflow(client, valid_form):
    _login_coordinator(client)
    submitted = client.post("/reports", data=valid_form).json()

    # Simulate notification service exception during incident confirmation
    with patch("app.services.notification_service.notify_new_incident", side_effect=RuntimeError("Notification system down")):
        confirmed = client.post(f"/reports/{submitted['id']}/confirm")
        assert confirmed.status_code == 201
        assert confirmed.json()["status"] == "CONFIRMED"
