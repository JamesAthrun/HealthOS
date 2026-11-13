from sqlalchemy import update

import app.photos as photos_module
from app.config import get_settings
from app.db import SessionLocal
from app.meal_ai import EstimatedNutrition
from app.models import User
from tests.test_meal_photos import authenticated

BODY = {"items": [{"name": "米饭", "quantity": 1, "unit": "碗"}]}


def _fake_estimate(monkeypatch):
    calls = []

    def fake(items, _settings):
        calls.append(len(items))
        return [EstimatedNutrition(kcal=230)]

    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-key")
    monkeypatch.setattr(photos_module, "estimate_nutrition", fake)
    return calls


def test_daily_ai_limit_blocks_after_quota_and_is_per_user(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_daily_limit", 3)
    calls = _fake_estimate(monkeypatch)
    alice = authenticated("alice")
    bob = authenticated("bob")
    for client in (alice, bob):
        client.put("/api/ai-consent")

    assert [alice.post("/api/meal-text/estimate", json=BODY).status_code for _ in range(3)] == [200] * 3
    blocked = alice.post("/api/meal-text/estimate", json=BODY)
    assert blocked.status_code == 429
    assert "每天 3 次" in blocked.json()["detail"]
    assert len(calls) == 3  # 超出后不会再调用 AI
    # 别人不受影响
    assert bob.post("/api/meal-text/estimate", json=BODY).status_code == 200


def test_validation_failures_do_not_use_quota(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_daily_limit", 1)
    _fake_estimate(monkeypatch)
    client = authenticated("alice")
    client.put("/api/ai-consent")
    assert client.post("/api/meal-text/estimate", json={"items": []}).status_code == 422
    assert client.post("/api/meal-recognitions/preview", json={"photo_ids": ["00000000-0000-0000-0000-000000000000"]}).status_code == 404
    assert client.post("/api/meal-text/estimate", json=BODY).status_code == 200


def test_admin_is_not_limited(monkeypatch):
    monkeypatch.setattr(get_settings(), "ai_daily_limit", 1)
    _fake_estimate(monkeypatch)
    client = authenticated("boss")
    with SessionLocal() as db:
        db.execute(update(User).where(User.username == "boss").values(is_admin=True))
        db.commit()
    client.put("/api/ai-consent")
    assert [client.post("/api/meal-text/estimate", json=BODY).status_code for _ in range(3)] == [200] * 3
