from app.config import get_settings
from app.meal_ai import MealRecognition
import app.photos as photos_module
from tests.test_meal_photos import authenticated, image_bytes, upload

MEAL = {
    "eaten_at": "2026-11-06T12:00:00+08:00",
    "meal_type": "lunch",
    "food_items": [{"name": "米饭", "quantity": 1, "unit": "碗", "kcal": 230}],
}


def _recognition(name: str = "牛肉面") -> MealRecognition:
    return MealRecognition.model_validate({
        "meal_type": "dinner",
        "food_items": [{"name": name, "quantity": 1, "unit": "碗（约500g）", "kcal": 550, "confidence": 0.8}],
        "overall_confidence": 0.8,
        "warnings": [],
    })


def _confirmed_meal(client, monkeypatch, colors=("red", "blue")):
    ids = [upload(client, image_bytes(color)).json()["id"] for color in colors]
    client.put("/api/ai-consent")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-key")
    monkeypatch.setattr(photos_module, "recognize_meal_photos", lambda images, _s, note=None, hint=None: _recognition())
    assert client.post("/api/meal-recognitions", json={"photo_ids": ids}).status_code == 200
    meal = client.post(f"/api/meal-photos/{ids[0]}/confirm", json={**MEAL, "photo_ids": ids})
    assert meal.status_code == 201
    return meal.json(), ids


def test_confirm_links_all_photos_and_meal_lists_them(monkeypatch):
    client = authenticated("alice")
    meal, ids = _confirmed_meal(client, monkeypatch)
    assert meal["photo_ids"] == ids
    assert client.get(f"/api/meals/{meal['id']}").json()["photo_ids"] == ids
    assert client.get("/api/meals").json()[0]["photo_ids"] == ids


def test_manual_meal_has_no_photos_and_can_be_created_with_photos():
    client = authenticated("alice")
    plain = client.post("/api/meals", json=MEAL).json()
    assert plain["photo_ids"] == []
    photo = upload(client, image_bytes("gold")).json()["id"]
    with_photo = client.post("/api/meals", json={**MEAL, "photo_ids": [photo]})
    assert with_photo.status_code == 201
    assert with_photo.json()["photo_ids"] == [photo]


def test_patch_replaces_adds_and_removes_photos(monkeypatch):
    client = authenticated("alice")
    meal, ids = _confirmed_meal(client, monkeypatch)
    new_photo = upload(client, image_bytes("green")).json()["id"]

    # 去掉第一张、加一张新的：新的第一张成为封面
    patched = client.patch(f"/api/meals/{meal['id']}", json={"photo_ids": [ids[1], new_photo]})
    assert patched.status_code == 200
    assert patched.json()["photo_ids"] == [ids[1], new_photo]
    # 移除的照片仍然可以查看（只是不再属于这一餐）
    assert client.get(f"/api/meal-photos/{ids[0]}").status_code == 200

    # 不传 photo_ids 时照片不变
    other_change = client.patch(f"/api/meals/{meal['id']}", json={"notes": "改备注"})
    assert other_change.json()["photo_ids"] == [ids[1], new_photo]

    cleared = client.patch(f"/api/meals/{meal['id']}", json={"photo_ids": []})
    assert cleared.json()["photo_ids"] == []


def test_patch_rejects_other_users_photos_and_too_many(monkeypatch):
    alice = authenticated("alice")
    bob = authenticated("bob")
    meal, ids = _confirmed_meal(alice, monkeypatch)
    bobs = upload(bob, image_bytes("green")).json()["id"]
    assert alice.patch(f"/api/meals/{meal['id']}", json={"photo_ids": [bobs]}).status_code == 404
    assert alice.patch(f"/api/meals/{meal['id']}", json={"photo_ids": ids * 3}).status_code == 422
    assert alice.get(f"/api/meals/{meal['id']}").json()["photo_ids"] == ids
    assert bob.patch(f"/api/meals/{meal['id']}", json={"photo_ids": [bobs]}).status_code == 404


def test_preview_recognition_does_not_save(monkeypatch):
    client = authenticated("alice")
    meal, ids = _confirmed_meal(client, monkeypatch)
    calls = []

    def fake(images, _settings, note=None, hint=None):
        calls.append((len(images), note))
        return _recognition("番茄鸡蛋面")

    monkeypatch.setattr(photos_module, "recognize_meal_photos", fake)
    # 已确认的照片也可以重新识别（只返回草稿）
    preview = client.post("/api/meal-recognitions/preview", json={"photo_ids": ids, "note": " 只吃了一半 "})
    assert preview.status_code == 200
    assert preview.json()["food_items"][0]["name"] == "番茄鸡蛋面"
    assert calls == [(2, "只吃了一半")]
    assert client.get(f"/api/meals/{meal['id']}").json()["food_items"][0]["name"] == "米饭"


def test_preview_requires_consent_and_own_photos(monkeypatch):
    alice = authenticated("alice")
    bob = authenticated("bob")
    photo = upload(alice, image_bytes("red")).json()["id"]
    bobs = upload(bob, image_bytes("blue")).json()["id"]
    assert alice.post("/api/meal-recognitions/preview", json={"photo_ids": [photo]}).status_code == 403
    alice.put("/api/ai-consent")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-key")
    monkeypatch.setattr(photos_module, "recognize_meal_photos", lambda images, _s, note=None, hint=None: _recognition())
    assert alice.post("/api/meal-recognitions/preview", json={"photo_ids": [photo, bobs]}).status_code == 404
    assert alice.post("/api/meal-recognitions/preview", json={"photo_ids": []}).status_code == 422


def test_deleting_meal_keeps_photo_files(monkeypatch):
    client = authenticated("alice")
    meal, ids = _confirmed_meal(client, monkeypatch)
    assert client.delete(f"/api/meals/{meal['id']}").status_code == 204
    assert client.get(f"/api/meal-photos/{ids[0]}").status_code == 200
