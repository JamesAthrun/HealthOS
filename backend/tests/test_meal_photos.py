import io

from PIL import Image

import app.photos as photos_module
from app.meal_ai import MealRecognition, _strip_code_fence
from app.config import get_settings
from tests.conftest import create_user, login, new_client


def test_ai_response_code_fence_is_stripped():
    assert _strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}\n'
    assert _strip_code_fence(' {"a": 1} ') == '{"a": 1}'


def test_ai_busy_503_backs_off_and_retries_keeping_json_mode(monkeypatch):
    import httpx

    import app.meal_ai as meal_ai

    sent = []
    waits = []
    good = {
        "meal_type": "lunch",
        "food_items": [{"name": "米饭", "quantity": 1, "unit": "碗", "kcal": 200, "confidence": 0.8}],
        "overall_confidence": 0.8,
    }
    # 前两次繁忙，第三次成功：繁忙重试不占用“输出不合格”的那次重试
    statuses = [503, 429, 200]

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, url, headers, json):
            sent.append(dict(json))
            request = httpx.Request("POST", url)
            code = statuses[len(sent) - 1]
            if code != 200:
                return httpx.Response(code, request=request, json={"error": {"message": "busy"}})
            import json as _json
            return httpx.Response(200, request=request, json={"choices": [{"message": {"content": _json.dumps(good)}}]})

    monkeypatch.setattr(meal_ai.httpx, "Client", FakeClient)
    monkeypatch.setattr(meal_ai, "_sleep", waits.append)
    settings = get_settings().model_copy(update={"deepseek_api_key": "test-key"})
    assert meal_ai.recognize_meal(b"jpeg", settings).food_items[0].name == "米饭"
    assert waits == [1.0, 3.0]
    assert all("response_format" in body for body in sent)

    # 一直繁忙：等两次后放弃，报 503
    sent.clear()
    waits.clear()
    statuses[:] = [503] * 10
    try:
        meal_ai.recognize_meal(b"jpeg", settings)
        raise AssertionError("expected AIProviderError")
    except meal_ai.AIProviderError as exc:
        assert exc.code == "AI_HTTP_503"
    assert waits == [1.0, 3.0]
    assert len(sent) == 4  # 1 次 + 2 次繁忙重试 + 1 次常规重试


def test_ai_meal_type_variants_are_normalized():
    item = {"name": "米饭", "quantity": 1, "unit": "碗", "kcal": 200, "confidence": 0.8}
    base = {"food_items": [item], "overall_confidence": 0.8, "warnings": []}
    assert MealRecognition.model_validate({**base, "meal_type": "午餐"}).meal_type == "lunch"
    assert MealRecognition.model_validate({**base, "meal_type": " Dinner "}).meal_type == "dinner"
    unknown = MealRecognition.model_validate({**base, "meal_type": "不确定"})
    assert unknown.meal_type == "snack"
    assert unknown.warnings == ["未能判断餐次，请确认"]


def test_ai_optional_nutrients_may_be_missing_or_null():
    item = {"name": "米饭", "quantity": 1, "unit": "碗", "kcal": 200, "confidence": 0.8}
    base = {"meal_type": "lunch", "overall_confidence": 0.8}
    missing = MealRecognition.model_validate({**base, "food_items": [item]})
    assert missing.food_items[0].sodium_mg is None
    with_values = MealRecognition.model_validate(
        {**base, "food_items": [{**item, "fiber_g": 0.6, "sugar_g": None, "sodium_mg": 5}]}
    )
    assert with_values.food_items[0].fiber_g == 0.6
    assert with_values.food_items[0].sugar_g is None


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


def test_photo_upload_accepts_iphone_heic():
    client = authenticated("alice")
    output = io.BytesIO()
    Image.new("RGB", (1200, 900), color="olive").save(output, format="HEIF")

    created = client.post(
        "/api/meal-photos", content=output.getvalue(), headers={"Content-Type": "image/heic"}
    )
    assert created.status_code == 201
    assert created.json()["content_type"] == "image/jpeg"
    assert (created.json()["width"], created.json()["height"]) == (1200, 900)


def test_photo_upload_accepts_iphone_mpo_jpeg():
    client = authenticated("alice")
    output = io.BytesIO()
    primary = Image.new("RGB", (1200, 900), color="olive")
    gain_map = Image.new("RGB", (600, 450), color="gray")
    primary.save(output, format="MPO", save_all=True, append_images=[gain_map])
    assert Image.open(io.BytesIO(output.getvalue())).format == "MPO"

    created = client.post(
        "/api/meal-photos", content=output.getvalue(), headers={"Content-Type": "image/jpeg"}
    )
    assert created.status_code == 201
    assert (created.json()["width"], created.json()["height"]) == (1200, 900)


def test_photo_upload_applies_exif_orientation():
    client = authenticated("alice")
    exif = Image.Exif()
    exif[0x0112] = 6  # 顺时针旋转 90° 显示，iPhone 竖拍常见
    output = io.BytesIO()
    Image.new("RGB", (1200, 900), color="olive").save(output, format="JPEG", exif=exif)

    created = client.post(
        "/api/meal-photos", content=output.getvalue(), headers={"Content-Type": "image/jpeg"}
    )
    assert created.status_code == 201
    assert (created.json()["width"], created.json()["height"]) == (900, 1200)


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
        lambda _image, _settings, hint=None: MealRecognition.model_validate(
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


def test_user_hint_triggers_fresh_recognition_until_confirmed(monkeypatch):
    client = authenticated("alice")
    photo_id = upload(client, image_bytes("navy")).json()["id"]
    client.put("/api/ai-consent")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test-key")
    calls = []

    def fake(_image, _settings, hint=None):
        calls.append(hint)
        name = "牛肉面" if hint else "米饭"
        return MealRecognition.model_validate({
            "meal_type": "lunch",
            "food_items": [{"name": name, "quantity": 1, "unit": "碗", "kcal": 500, "confidence": 0.8}],
            "overall_confidence": 0.8,
        })

    monkeypatch.setattr(photos_module, "recognize_meal", fake)
    analyze = f"/api/meal-photos/{photo_id}/analyze"
    assert client.post(analyze).json()["result"]["food_items"][0]["name"] == "米饭"
    # 没有说明时复用结果，不重复调用 AI
    assert client.post(analyze).json()["result"]["food_items"][0]["name"] == "米饭"
    assert calls == [None]

    retried = client.post(analyze, json={"hint": "  这是一碗牛肉面  "})
    assert retried.status_code == 200
    assert retried.json()["result"]["food_items"][0]["name"] == "牛肉面"
    assert calls == [None, "这是一碗牛肉面"]
    assert client.post(analyze, json={"hint": "x" * 201}).status_code == 422

    meal = {
        "eaten_at": "2026-10-31T12:00:00+08:00",
        "meal_type": "lunch",
        "food_items": [{"name": "牛肉面", "quantity": 1, "unit": "碗", "kcal": 500}],
    }
    assert client.post(f"/api/meal-photos/{photo_id}/confirm", json=meal).status_code == 201
    assert client.post(analyze, json={"hint": "只吃了一半"}).status_code == 409
