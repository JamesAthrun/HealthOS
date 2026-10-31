import io

from PIL import Image

import app.photos as photos_module
from app.meal_ai import MealRecognition
from app.config import get_settings
from tests.conftest import create_user, login, new_client


def authenticated(username: str):
    create_user(username)
    client = new_client()
    assert login(client, username).status_code == 200
    return client


def image_bytes(color: str = "tomato") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (2400, 1800), color=color).save(
        output,
        format="PNG",
        pnginfo=None,
    )
    return output.getvalue()


def upload(client, raw: bytes):
    return client.post(
        "/api/meal-photos",
        content=raw,
        headers={"Content-Type": "image/png"},
    )


def test_photo_upload_normalizes_deduplicates_and_stays_private():
    alice = authenticated("alice")
    bob = authenticated("bob")
    raw = image_bytes()

    created = upload(alice, raw)
    assert created.status_code == 201
    photo = created.json()
    assert photo["content_type"] == "image/jpeg"
    assert max(photo["width"], photo["height"]) == 1600
    assert photo["byte_size"] < len(raw)

    duplicate = upload(alice, raw)
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == photo["id"]

    downloaded = alice.get(f"/api/meal-photos/{photo['id']}")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"].startswith("image/jpeg")
    assert downloaded.headers["cache-control"] == "private, no-store"
    assert downloaded.content.startswith(b"\xff\xd8")
    assert bob.get(f"/api/meal-photos/{photo['id']}").status_code == 404


def test_photo_upload_rejects_invalid_content():
    client = authenticated("alice")
    response = upload(client, b"not really a photo")
    assert response.status_code == 415


def test_ai_draft_requires_consent_and_only_counts_after_confirmation(monkeypatch):
    client = authenticated("alice")
    photo_id = upload(client, image_bytes("gold")).json()["id"]
    assert client.post(f"/api/meal-photos/{photo_id}/analyze").status_code == 403

    consent = client.put("/api/ai-consent")
    assert consent.status_code == 200
    assert consent.json()["granted"] is True

    settings = get_settings()
    monkeypatch.setattr(settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(
        photos_module,
        "recognize_meal",
        lambda _image, _settings: MealRecognition.model_validate(
            {
                "meal_type": "lunch",
                "food_items": [
                    {
                        "name": "番茄炒蛋",
                        "quantity": 1,
                        "unit": "份",
                        "kcal": 420,
                        "protein_g": 22,
                        "carbs_g": 18,
                        "fat_g": 28,
                        "confidence": 0.78,
                    }
                ],
                "overall_confidence": 0.78,
                "warnings": ["份量需要确认"],
            }
        ),
    )
    analyzed = client.post(f"/api/meal-photos/{photo_id}/analyze")
    assert analyzed.status_code == 200
    assert analyzed.json()["status"] == "succeeded"
    assert analyzed.json()["result"]["food_items"][0]["name"] == "番茄炒蛋"

    # AI 草稿不会进入正式统计。
    before = client.get("/api/dashboard/today?on=2026-10-31").json()
    assert before["summary"]["kcal"] == 0

    corrected = {
        "eaten_at": "2026-10-31T12:00:00+08:00",
        "meal_type": "lunch",
        "notes": "用户确认后的估算",
        "food_items": [
            {
                "name": "番茄炒蛋",
                "quantity": 1,
                "unit": "份",
                "kcal": 400,
                "protein_g": 20,
                "carbs_g": 16,
                "fat_g": 26,
            }
        ],
    }
    confirmed = client.post(f"/api/meal-photos/{photo_id}/confirm", json=corrected)
    assert confirmed.status_code == 201
    meal_id = confirmed.json()["id"]
    assert confirmed.json()["status"] == "confirmed"

    after = client.get("/api/dashboard/today?on=2026-10-31").json()
    assert after["summary"]["kcal"] == 400

    # 重复确认是幂等的，不会生成第二餐。
    again = client.post(f"/api/meal-photos/{photo_id}/confirm", json=corrected)
    assert again.status_code == 201
    assert again.json()["id"] == meal_id
    assert len(client.get("/api/meals").json()) == 1

    assert client.delete("/api/ai-consent").json()["granted"] is False
