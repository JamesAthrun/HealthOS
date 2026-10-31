from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import User, UserSession
from tests.conftest import create_user, login, new_client


def test_login_sets_httponly_cookie_and_me_returns_user():
    create_user("alice", display_name="Alice")
    client = new_client()

    resp = login(client, "alice")

    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Alice"
    set_cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert client.get("/api/me").json()["username"] == "alice"


def test_username_is_case_insensitive():
    create_user("alice")
    assert login(new_client(), "ALICE").status_code == 200


def test_wrong_password_and_unknown_user_return_same_error():
    create_user("alice")
    wrong = login(new_client(), "alice", "wrong-password")
    unknown = login(new_client(), "nobody", "wrong-password")

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_account_locks_after_five_failures():
    create_user("alice")
    client = new_client()
    for _ in range(5):
        assert login(client, "alice", "wrong-password").status_code == 401

    # 锁定期间即使密码正确也无法登录
    assert login(client, "alice").status_code == 401


def test_ip_rate_limit():
    client = new_client()
    codes = [login(client, "nobody", "x").status_code for _ in range(11)]
    assert codes[-1] == 429


def test_me_requires_valid_session():
    assert new_client().get("/api/me").status_code == 401

    client = new_client()
    client.cookies.set("healthos_session", "forged-token")
    assert client.get("/api/me").status_code == 401


def test_logout_invalidates_session():
    create_user("alice")
    client = new_client()
    login(client, "alice")
    token = client.cookies.get("healthos_session")

    assert client.post("/api/auth/logout").status_code == 204

    replay = new_client()
    replay.cookies.set("healthos_session", token)
    assert replay.get("/api/me").status_code == 401


def test_expired_session_is_rejected():
    create_user("alice")
    client = new_client()
    login(client, "alice")
    with SessionLocal() as db:
        db.execute(update(UserSession).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
        db.commit()

    assert client.get("/api/me").status_code == 401


def test_session_token_and_password_are_not_stored_in_plaintext():
    create_user("alice", password="password123")
    client = new_client()
    login(client, "alice")
    token = client.cookies.get("healthos_session")

    with SessionLocal() as db:
        user = db.scalar(select(User))
        session = db.scalar(select(UserSession))
    assert "password123" not in user.password_hash
    assert user.password_hash.startswith("$argon2")
    assert token.encode() != session.id_hash


def test_two_users_each_see_only_themselves():
    create_user("alice")
    create_user("bob")
    client_a, client_b = new_client(), new_client()
    login(client_a, "alice")
    login(client_b, "bob")

    assert client_a.get("/api/me").json()["username"] == "alice"
    assert client_b.get("/api/me").json()["username"] == "bob"


def test_change_password_revokes_other_sessions():
    create_user("alice")
    phone, laptop = new_client(), new_client()
    login(phone, "alice")
    login(laptop, "alice")

    bad = phone.post("/api/me/password", json={"current_password": "nope", "new_password": "newpassword1"})
    assert bad.status_code == 400

    ok = phone.post("/api/me/password", json={"current_password": "password123", "new_password": "newpassword1"})
    assert ok.status_code == 204
    assert phone.get("/api/me").status_code == 200
    assert laptop.get("/api/me").status_code == 401
    assert login(new_client(), "alice", "password123").status_code == 401
    assert login(new_client(), "alice", "newpassword1").status_code == 200


def test_new_password_must_be_long_enough():
    create_user("alice")
    client = new_client()
    login(client, "alice")
    resp = client.post("/api/me/password", json={"current_password": "password123", "new_password": "short"})
    assert resp.status_code == 422
