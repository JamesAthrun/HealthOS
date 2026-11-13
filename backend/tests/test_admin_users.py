import uuid

from sqlalchemy import func, select, update

from app.audit import set_tenant_context
from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditEvent, FoodItem, Meal, MealPhoto, User
from tests.conftest import create_user, login, new_client
from tests.test_meal_photos import image_bytes, upload


def _admin():
    create_user("boss")
    with SessionLocal() as db:
        db.execute(update(User).where(User.username == "boss").values(is_admin=True))
        db.commit()
    client = new_client()
    login(client, "boss")
    return client


def _user_id(username: str) -> str:
    with SessionLocal() as db:
        return str(db.scalar(select(User.id).where(User.username == username)))


def test_admin_lists_users_with_last_login_and_lock_state():
    admin = _admin()
    create_user("alice")
    login(new_client(), "alice")
    create_user("bob")
    for _ in range(5):
        login(new_client(), "bob", "wrong-password")

    users = {u["username"]: u for u in admin.get("/api/admin/users").json()}
    assert set(users) == {"boss", "alice", "bob"}
    assert users["boss"]["is_admin"] is True
    assert users["alice"]["last_login_at"] is not None
    assert users["bob"]["last_login_at"] is None
    assert users["bob"]["locked"] is True
    assert "password_hash" not in users["alice"]


def test_reset_password_gives_temporary_password_unlocks_and_logs_out():
    admin = _admin()
    create_user("alice")
    alice = new_client()
    login(alice, "alice")
    for _ in range(5):
        login(new_client(), "alice", "wrong-password")

    resp = admin.post(f"/api/admin/users/{_user_id('alice')}/reset-password")
    assert resp.status_code == 200
    temporary = resp.json()["temporary_password"]
    assert len(temporary) == 10
    assert alice.get("/api/me").status_code == 401  # 旧会话失效
    assert login(new_client(), "alice", "password123").status_code == 401
    assert login(new_client(), "alice", temporary).status_code == 200
    # 不能用这个接口改自己的密码
    assert admin.post(f"/api/admin/users/{_user_id('boss')}/reset-password").status_code == 400


def test_delete_user_removes_all_data_and_photo_files():
    admin = _admin()
    create_user("alice")
    alice = new_client()
    login(alice, "alice")
    photo = upload(alice, image_bytes("red")).json()["id"]
    alice.post("/api/meals", json={
        "eaten_at": "2026-11-11T12:00:00+08:00", "meal_type": "lunch",
        "food_items": [{"name": "米饭", "quantity": 1, "unit": "碗", "kcal": 230}], "photo_ids": [photo],
    })
    alice_id = _user_id("alice")
    photo_dir = get_settings().photo_dir / alice_id
    assert photo_dir.is_dir()

    wrong = admin.post(f"/api/admin/users/{alice_id}/delete", json={"confirm_username": "bob"})
    assert wrong.status_code == 400
    resp = admin.post(f"/api/admin/users/{alice_id}/delete", json={"confirm_username": " Alice "})
    assert resp.status_code == 204

    assert alice.get("/api/me").status_code == 401
    assert not photo_dir.exists()
    uid = uuid.UUID(alice_id)
    with SessionLocal() as db:
        assert db.get(User, uid) is None
        set_tenant_context(db, uid)
        for model in (Meal, FoodItem, MealPhoto):
            assert db.scalar(select(func.count()).select_from(model).where(model.user_id == uid)) == 0
        admin_id = uuid.UUID(_user_id("boss"))
        db.rollback()
        set_tenant_context(db, admin_id)
        events = list(db.scalars(select(AuditEvent.event_type).where(AuditEvent.user_id == admin_id)))
        assert "admin_user_deleted" in events
    assert {u["username"] for u in admin.get("/api/admin/users").json()} == {"boss"}


def test_admin_cannot_delete_self_and_non_admin_is_forbidden():
    admin = _admin()
    assert admin.post(f"/api/admin/users/{_user_id('boss')}/delete", json={"confirm_username": "boss"}).status_code == 400
    create_user("alice")
    alice = new_client()
    login(alice, "alice")
    assert alice.get("/api/admin/users").status_code == 403
    assert alice.post(f"/api/admin/users/{_user_id('boss')}/reset-password").status_code == 403
    assert alice.post(f"/api/admin/users/{_user_id('boss')}/delete", json={"confirm_username": "boss"}).status_code == 403
    assert admin.post(f"/api/admin/users/{uuid.uuid4()}/reset-password").status_code == 404
