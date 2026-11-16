import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

import app.photos as photos_module
from app.config import get_settings
from app.db import SessionLocal
from app.meal_ai import AIProviderError, EstimatedNutrition
from app.models import AICall, BackupRun, User
from tests.conftest import create_user, login, new_client

MEAL = {
    "eaten_at": "2026-11-13T12:00:00+08:00",
    "meal_type": "lunch",
    "food_items": [{"name": "米饭", "quantity": 1, "unit": "碗", "kcal": 230}],
}
ESTIMATE = {"items": [{"name": "米饭", "quantity": 1, "unit": "碗"}]}


def _admin():
    create_user("boss")
    with SessionLocal() as db:
        db.execute(update(User).where(User.username == "boss").values(is_admin=True))
        db.commit()
    client = new_client()
    login(client, "boss")
    return client


def test_ai_calls_are_tracked_with_outcome_and_duration(monkeypatch):
    create_user("alice")
    alice = new_client()
    login(alice, "alice")
    alice.put("/api/ai-consent")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-key")
    results = iter([[EstimatedNutrition(kcal=230)], AIProviderError("AI_TIMEOUT")])

    def fake(_items, _settings):
        result = next(results)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(photos_module, "estimate_nutrition", fake)
    assert alice.post("/api/meal-text/estimate", json=ESTIMATE).status_code == 200
    assert alice.post("/api/meal-text/estimate", json=ESTIMATE).status_code == 502
    with SessionLocal() as db:
        calls = list(db.scalars(select(AICall).order_by(AICall.started_at)))
    assert [(c.kind, c.outcome) for c in calls] == [("estimate", "ok"), ("estimate", "AI_TIMEOUT")]
    assert all(c.duration_ms is not None for c in calls)


def test_dashboard_shows_usage_ai_server_and_security(monkeypatch):
    admin = _admin()
    create_user("alice")
    alice = new_client()
    login(alice, "alice")
    alice.post("/api/meals", json=MEAL)
    alice.post("/api/meals", json=MEAL)
    for _ in range(2):
        login(new_client(), "alice", "wrong-password")
    alice_id = alice.get("/api/me").json()["id"]
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        db.add_all([
            AICall(user_id=uuid.UUID(alice_id), kind="photos", started_at=now, duration_ms=12000, outcome="ok"),
            AICall(user_id=uuid.UUID(alice_id), kind="text", started_at=now, duration_ms=45000, outcome="AI_TIMEOUT"),
            AICall(user_id=uuid.UUID(alice_id), kind="photos", started_at=now - timedelta(days=10), duration_ms=1, outcome="ok"),
            BackupRun(finished_at=now - timedelta(hours=2), ok=True, db_bytes=120_000, photos_bytes=17_000_000, message="ok"),
            BackupRun(finished_at=now - timedelta(hours=1), ok=False, message="pg_dump failed"),
        ])
        db.commit()

    resp = admin.get("/api/admin/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    users = {u["username"]: u for u in data["users"]}
    assert users["alice"]["meals_7d"] == 2
    assert users["alice"]["ai_7d"] == 2  # 10 天前的不算
    assert users["boss"]["meals_7d"] == 0

    ai = data["ai"]
    assert ai["calls_7d"] == 2 and ai["failed_7d"] == 1
    assert ai["by_kind_7d"] == {"photos": 1, "text": 1}
    assert ai["failures_7d"] == [{"outcome": "AI_TIMEOUT", "count": 1}]
    assert ai["avg_ms_7d"] == 12000

    server = data["server"]
    assert server["disk_total_bytes"] > server["disk_free_bytes"] > 0
    assert server["last_backup"]["ok"] is False
    assert server["last_backup"]["message"] == "pg_dump failed"
    assert server["last_ok_backup_at"] is not None

    events = [(e["username"], e["event_type"], e["outcome"]) for e in data["security_events"]]
    assert events.count(("alice", "login", "denied")) == 2
    # 正常登录不出现在安全事件里
    assert ("alice", "login", "success") not in events
    # 总览不包含任何记录内容
    assert "米饭" not in resp.text


def test_dashboard_is_admin_only():
    create_user("alice")
    alice = new_client()
    login(alice, "alice")
    assert alice.get("/api/admin/dashboard").status_code == 403
    assert new_client().get("/api/admin/dashboard").status_code == 401
