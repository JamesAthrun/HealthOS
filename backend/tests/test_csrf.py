from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import create_user, login, new_client


def test_write_request_without_origin_is_rejected():
    create_user("alice")
    client = TestClient(app)
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert resp.status_code == 403


def test_write_request_from_other_site_is_rejected():
    create_user("alice")
    client = TestClient(app, headers={"Origin": "https://evil.example"})
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert resp.status_code == 403


def test_referer_from_allowed_origin_is_accepted():
    create_user("alice")
    client = TestClient(app, headers={"Referer": "http://testserver/login/"})
    resp = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert resp.status_code == 200


def test_read_request_does_not_need_origin():
    assert TestClient(app).get("/api/health").json() == {"status": "ok"}


def test_post_with_method_override_reaches_patch_and_put_routes():
    create_user("alice")
    client = new_client()
    login(client, "alice")
    meal = client.post("/api/meals", json={
        "eaten_at": "2026-11-11T12:00:00+08:00",
        "meal_type": "lunch",
        "food_items": [{"name": "米饭", "quantity": 1, "unit": "碗", "kcal": 230}],
    }).json()

    patched = client.post(
        f"/api/meals/{meal['id']}", json={"notes": "改过"}, headers={"X-HTTP-Method-Override": "patch"}
    )
    assert patched.status_code == 200
    assert patched.json()["notes"] == "改过"

    put = client.post("/api/planning-consent", headers={"X-HTTP-Method-Override": "PUT"})
    assert put.status_code == 200 and put.json()["granted"] is True

    # 不允许改写成 GET 等其他方法；没有 POST 路由时照常 405
    assert client.post(f"/api/meals/{meal['id']}", headers={"X-HTTP-Method-Override": "GET"}).status_code == 405


def test_method_override_still_requires_allowed_origin():
    create_user("alice")
    client = new_client()
    login(client, "alice")
    evil = TestClient(app, headers={"Origin": "https://evil.example"}, cookies=client.cookies)
    resp = evil.post("/api/planning-consent", headers={"X-HTTP-Method-Override": "PUT"})
    assert resp.status_code == 403
