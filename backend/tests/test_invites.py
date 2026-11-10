import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import AuditEvent, InviteCode, User
from tests.conftest import create_user, login, new_client


def _admin_client():
    create_user("boss")
    with SessionLocal() as db:
        db.execute(update(User).where(User.username == "boss").values(is_admin=True))
        db.commit()
    client = new_client()
    login(client, "boss")
    return client


def _register(code: str, username: str = "newbie", password: str = "password123", **extra):
    client = new_client()
    resp = client.post(
        "/api/auth/register",
        json={"invite_code": code, "username": username, "password": password, **extra},
    )
    return client, resp


def test_admin_creates_invite_and_new_user_registers_and_is_logged_in():
    admin = _admin_client()
    created = admin.post("/api/admin/invites", json={"note": "妈妈"})
    assert created.status_code == 201
    body = created.json()
    code = body["code"]
    assert len(code) == 9 and code[4] == "-"
    assert body["status"] == "active" and body["note"] == "妈妈"
    assert body["code_hint"] == code.replace("-", "")[-4:]

    # 大小写、空格、连字符都无所谓
    client, resp = _register(" " + code.lower().replace("-", " ") + " ", username="NewBie", display_name="小新")
    assert resp.status_code == 201
    assert resp.json()["username"] == "newbie"
    assert resp.json()["display_name"] == "小新"
    assert resp.json()["is_admin"] is False
    assert client.get("/api/me").json()["username"] == "newbie"
    assert login(new_client(), "newbie").status_code == 200

    listed = admin.get("/api/admin/invites").json()
    assert listed[0]["status"] == "used"
    assert listed[0]["used_by_username"] == "newbie"
    assert "code" not in listed[0]
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id).where(User.username == "newbie"))
        assert db.scalar(select(AuditEvent.event_type).where(AuditEvent.user_id == user_id)) == "registered"


def test_invite_code_is_single_use():
    code = _admin_client().post("/api/admin/invites", json={}).json()["code"]
    assert _register(code, "first")[1].status_code == 201
    second = _register(code, "second")[1]
    assert second.status_code == 400
    assert login(new_client(), "second").status_code == 401


def test_invalid_expired_and_revoked_codes_are_rejected():
    admin = _admin_client()
    assert _register("ABCD-EFGH")[1].status_code == 400

    expired = admin.post("/api/admin/invites", json={}).json()
    with SessionLocal() as db:
        db.execute(
            update(InviteCode)
            .where(InviteCode.id == uuid.UUID(expired["id"]))
            .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        db.commit()
    assert _register(expired["code"])[1].status_code == 400

    revoked = admin.post("/api/admin/invites", json={}).json()
    assert admin.delete(f"/api/admin/invites/{revoked['id']}").status_code == 204
    assert _register(revoked["code"])[1].status_code == 400

    statuses = {i["id"]: i["status"] for i in admin.get("/api/admin/invites").json()}
    assert statuses[expired["id"]] == "expired"
    assert statuses[revoked["id"]] == "revoked"


def test_taken_username_does_not_consume_code():
    admin = _admin_client()
    code = admin.post("/api/admin/invites", json={}).json()["code"]
    resp = _register(code, username="boss")[1]
    assert resp.status_code == 409
    assert _register(code, username="other")[1].status_code == 201


def test_register_validates_username_and_password():
    code = _admin_client().post("/api/admin/invites", json={}).json()["code"]
    assert _register(code, username="有中文")[1].status_code == 422
    assert _register(code, username="ok_name", password="short")[1].status_code == 422
    assert _register(code, username="ok_name")[1].status_code == 201


def test_used_invite_cannot_be_revoked():
    admin = _admin_client()
    invite = admin.post("/api/admin/invites", json={}).json()
    _register(invite["code"])
    assert admin.delete(f"/api/admin/invites/{invite['id']}").status_code == 409


def test_invite_admin_endpoints_require_admin():
    create_user("alice")
    client = new_client()
    login(client, "alice")
    assert client.get("/api/admin/invites").status_code == 403
    assert client.post("/api/admin/invites", json={}).status_code == 403
    assert new_client().get("/api/admin/invites").status_code == 401


def test_invite_code_is_stored_hashed():
    code = _admin_client().post("/api/admin/invites", json={}).json()["code"]
    with SessionLocal() as db:
        stored = db.scalar(select(InviteCode))
        assert code.replace("-", "").encode() not in stored.code_hash
        assert stored.code_hint == code[-4:]
