def test_login_sets_session_and_logout_clears_it(client):
    assert client.get("/auth/me").json()["role"] == "USER"
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_login_rejects_role_that_does_not_match_account(client):
    client.cookies.clear()
    response = client.post("/auth/login", json={
        "email": "user@example.test",
        "password": "test-user-password-123",
        "role": "ADMIN",
    })
    assert response.status_code == 401


def test_demo_coordinator_and_admin_roles_are_verified(client):
    for email, password, role in [
        ("coordinator@example.test", "test-coordinator-password-123", "MANAGEMENT"),
        ("admin@example.test", "test-admin-password-123", "ADMIN"),
    ]:
        client.cookies.clear()
        response = client.post("/auth/login", json={
            "email": email, "password": password, "role": role,
        })
        assert response.status_code == 200
        assert response.json()["role"] == role
        assert client.get("/auth/me").json()["role"] == role


def test_report_api_rejects_anonymous_requests(client, valid_form):
    client.cookies.clear()
    assert client.get("/reports").status_code == 401
    assert client.post("/reports", data=valid_form).status_code == 401
    assert client.post("/reports/import/json", json=[{}]).status_code == 401


def test_users_can_only_view_their_own_reports(client, valid_form):
    own_report = client.post("/reports", data=valid_form).json()

    client.post("/auth/logout")
    coordinator_login = client.post("/auth/login", json={
        "email": "coordinator@example.test",
        "password": "test-coordinator-password-123",
        "role": "MANAGEMENT",
    })
    assert coordinator_login.status_code == 200
    other_report = client.post("/reports", data={
        **valid_form, "description": "Coordinator report for another area",
    }).json()

    client.post("/auth/logout")
    client.post("/auth/login", json={
        "email": "user@example.test",
        "password": "test-user-password-123",
        "role": "USER",
    })
    visible_ids = {report["id"] for report in client.get("/reports").json()}
    assert own_report["id"] in visible_ids
    assert other_report["id"] not in visible_ids
    assert client.get(f"/reports/{other_report['id']}").status_code == 404