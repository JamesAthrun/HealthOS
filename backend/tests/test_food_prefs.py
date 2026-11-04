from app.advice_service import AdviceContent, allergy_keywords, filter_meal_plan
from app.food_prefs import normalize_food_name
from tests.conftest import create_user, login, new_client


def authenticated(username: str):
    create_user(username)
    client = new_client()
    assert login(client, username).status_code == 200
    return client


def add_meal(client, eaten_at: str, *names: str):
    items = [{"name": n, "quantity": 1, "unit": "份", "kcal": 300} for n in names]
    response = client.post(
        "/api/meals", json={"eaten_at": eaten_at, "meal_type": "lunch", "food_items": items}
    )
    assert response.status_code == 201


def test_preferences_normalize_overwrite_and_delete():
    client = authenticated("alice")
    liked = client.put("/api/food-preferences", json={"food_name": "  Ｂeef  Noodles ", "sentiment": "like"})
    assert liked.status_code == 201
    assert liked.json()["food_name"] == "beef noodles"

    # 同一食物（全角/大小写不同）重新标记就覆盖
    flipped = client.put("/api/food-preferences", json={"food_name": "beef noodles", "sentiment": "dislike"})
    assert flipped.status_code == 200
    assert flipped.json()["id"] == liked.json()["id"]
    assert [p["sentiment"] for p in client.get("/api/food-preferences").json()] == ["dislike"]

    assert client.put("/api/food-preferences", json={"food_name": "   ", "sentiment": "like"}).status_code == 422
    assert client.put("/api/food-preferences", json={"food_name": "米饭", "sentiment": "love"}).status_code == 422

    assert client.delete(f"/api/food-preferences/{liked.json()['id']}").status_code == 204
    assert client.get("/api/food-preferences").json() == []


def test_preferences_are_isolated_and_capped(monkeypatch):
    import app.food_prefs as module

    alice = authenticated("alice")
    bob = authenticated("bob")
    pref = alice.put("/api/food-preferences", json={"food_name": "牛肉面", "sentiment": "like"}).json()
    assert bob.get("/api/food-preferences").json() == []
    assert bob.delete(f"/api/food-preferences/{pref['id']}").status_code == 404

    monkeypatch.setattr(module, "MAX_PREFERENCES", 2)
    alice.put("/api/food-preferences", json={"food_name": "米饭", "sentiment": "like"})
    assert alice.put("/api/food-preferences", json={"food_name": "面包", "sentiment": "like"}).status_code == 409
    # 已有食物仍然可以修改
    assert alice.put("/api/food-preferences", json={"food_name": "米饭", "sentiment": "dislike"}).status_code == 200


def test_frequent_foods_counts_recent_confirmed_meals_only():
    from datetime import datetime, timedelta, timezone

    client = authenticated("alice")
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=2)).isoformat()
    old = (now - timedelta(days=40)).isoformat()
    add_meal(client, recent, "米饭", "番茄炒蛋")
    add_meal(client, recent, "米饭 ", "青菜")
    add_meal(client, old, "汉堡", "汉堡")
    frequent = client.get("/api/food-preferences/frequent").json()
    assert frequent[0] == {"food_name": "米饭", "count": 2}
    assert "汉堡" not in [f["food_name"] for f in frequent]


def test_allergy_keywords():
    assert allergy_keywords("花生、虾过敏，乳糖不耐受") == ["花生", "虾", "乳糖"]
    assert allergy_keywords("无") == []
    assert allergy_keywords(None) == []
    assert normalize_food_name("ＡＢＣ  饭") == "abc 饭"


def _content(kind_items):
    return AdviceContent.model_validate({
        "summary": "s",
        "actions": [{"category": "diet", "action": "a", "rationale": "r", "evidence_refs": [], "confidence": "low"}],
        "meal_plan": [
            {"meal_type": meal, "items": [{"name": n, "portion": "1 份", "approx_kcal": 300} for n in names], "reason": "r"}
            for meal, names in kind_items
        ],
    })


def test_meal_plan_filter_drops_allergens_and_dislikes():
    content = _content([
        ("breakfast", ["花生酱吐司", "牛奶"]),
        ("lunch", ["虾仁炒蛋"]),
        ("dinner", ["西兰花炒牛肉", "鸡蛋羹", "米饭"]),
    ])
    context = {
        "plan": {"kind": "daily"},
        "profile": {"allergies": "花生、虾"},
        "food_preferences": {"dislikes": ["西兰花", "鸡"]},
    }
    filtered = filter_meal_plan(content, context)
    assert [(g.meal_type, [i.name for i in g.items]) for g in filtered.meal_plan] == [
        ("breakfast", ["牛奶"]),
        # 午餐只有含虾的菜，整组被去掉；“鸡”是单字，只精确匹配，不误伤“鸡蛋羹”
        ("dinner", ["鸡蛋羹", "米饭"]),
    ]
    weekly = filter_meal_plan(content, {**context, "plan": {"kind": "weekly"}})
    assert weekly.meal_plan == []


def test_old_advice_without_meal_plan_still_parses():
    old = AdviceContent.model_validate_json(
        '{"summary":"s","actions":[{"category":"diet","action":"a","rationale":"r","evidence_refs":[],"confidence":"low"}],"limitations":[]}'
    )
    assert old.meal_plan == []
