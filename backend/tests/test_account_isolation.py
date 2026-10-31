import pytest
from sqlalchemy import select

from app.audit import add_audit_event, set_tenant_context
from app.db import SessionLocal, engine
from app.models import AuditEvent, MealPhoto, User
from tests.conftest import create_user, login, new_client


def test_user_can_update_only_their_own_account_settings():
    create_user("alice", display_name="Alice")
    create_user("bob", display_name="Bob")
    alice, bob = new_client(), new_client()
    login(alice, "alice")
    login(bob, "bob")

    response = alice.put(
        "/api/me/settings",
        json={
            "display_name": "  爱丽丝  ",
            "timezone": "Europe/London",
            "locale": "en-GB",
        },
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "爱丽丝"
    assert response.json()["timezone"] == "Europe/London"
    assert response.json()["locale"] == "en-GB"
    assert bob.get("/api/me").json()["display_name"] == "Bob"
    assert bob.get("/api/me").json()["timezone"] == "Asia/Shanghai"
    assert bob.get("/api/me").json()["locale"] == "zh-CN"


@pytest.mark.parametrize(
    "change",
    [
        {"timezone": "Mars/Olympus"},
        {"locale": "english"},
        {"display_name": "   "},
        {"user_id": "00000000-0000-0000-0000-000000000000"},
    ],
)
def test_account_settings_reject_invalid_or_owner_fields(change):
    create_user("alice")
    client = new_client()
    login(client, "alice")
    body = {"display_name": "Alice", "timezone": "Asia/Shanghai", "locale": "zh-CN"}
    body.update(change)

    assert client.put("/api/me/settings", json=body).status_code == 422


def test_audit_event_list_and_direct_id_are_owner_scoped():
    create_user("alice")
    create_user("bob")
    alice, bob = new_client(), new_client()
    login(alice, "alice")
    login(bob, "bob")

    alice_events = alice.get("/api/me/audit-events").json()
    bob_events = bob.get("/api/me/audit-events").json()
    assert {event["event_type"] for event in alice_events} == {"login"}
    assert {event["event_type"] for event in bob_events} == {"login"}

    bob_event_id = bob_events[0]["id"]
    hidden = alice.get(f"/api/me/audit-events/{bob_event_id}")
    assert hidden.status_code == 404
    assert hidden.json() == {"detail": "记录不存在"}
    assert bob.get(f"/api/me/audit-events/{bob_event_id}").status_code == 200


def test_security_sensitive_actions_create_minimal_audit_events():
    create_user("alice")
    client = new_client()
    assert login(client, "alice", "wrong-password").status_code == 401
    assert login(client, "alice").status_code == 200
    assert (
        client.put(
            "/api/me/settings",
            json={"display_name": "Alice", "timezone": "Asia/Shanghai", "locale": "zh-CN"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/me/password",
            json={"current_password": "password123", "new_password": "newpassword1"},
        ).status_code
        == 204
    )

    events = client.get("/api/me/audit-events").json()
    assert {(event["event_type"], event["outcome"]) for event in events} == {
        ("login", "denied"),
        ("login", "success"),
        ("settings_changed", "success"),
        ("password_changed", "success"),
    }
    assert all(set(event) == {"id", "event_type", "outcome", "ip_address", "created_at"} for event in events)


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL RLS integration test")
def test_postgres_rls_blocks_direct_cross_user_query():
    alice = create_user("alice")
    bob = create_user("bob")

    with SessionLocal() as db:
        add_audit_event(
            db,
            user_id=alice.id,
            event_type="test",
            outcome="success",
            ip_address=None,
        )
        db.commit()

    with SessionLocal() as db:
        event = add_audit_event(
            db,
            user_id=bob.id,
            event_type="test",
            outcome="success",
            ip_address=None,
        )
        db.commit()
        bob_event_id = event.id

    with SessionLocal() as db:
        set_tenant_context(db, alice.id)
        assert db.scalar(select(AuditEvent).where(AuditEvent.id == bob_event_id)) is None
        assert db.scalar(select(User).where(User.id == alice.id)) is not None

    with SessionLocal() as db:
        set_tenant_context(db, bob.id)
        photo = MealPhoto(
            user_id=bob.id,
            storage_key=f"{bob.id}/rls-test.jpg",
            sha256="0" * 64,
            content_type="image/jpeg",
            byte_size=3,
            width=1,
            height=1,
        )
        db.add(photo)
        db.commit()
        bob_photo_id = photo.id

    with SessionLocal() as db:
        set_tenant_context(db, alice.id)
        assert db.scalar(select(MealPhoto).where(MealPhoto.id == bob_photo_id)) is None
