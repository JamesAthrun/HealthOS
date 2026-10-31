from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import create_user


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
