from datetime import date, datetime, timedelta, timezone

import pytest

from tests.conftest import create_user, login, new_client


def authenticated(username: str):
    create_user(username)
    client = new_client()
    assert login(client, username).status_code == 200
    return client


def test_profile_and_kcal_reference():
    client = authenticated("alice")
    assert client.get("/api/profile").status_code == 404

    body = {
        "birth_year": date.today().year - 36,
        "sex": "male",
        "height_cm": 180,
        "weight_kg": 80,
        "activity_level": "moderate",
        "dietary_preferences": "少辣",
        "allergies": "花生",
        "daily_kcal_target": 2300,
    }
    saved = client.put("/api/profile", json=body)
    assert saved.status_code == 200
    assert saved.json()["daily_kcal_target"] == 2300
    assert client.get("/api/profile").json()["allergies"] == "花生"

    reference = client.get("/api/profile/kcal-reference")
    assert reference.status_code == 200
    assert reference.json() == {
        "maintenance_kcal": 2712,
        "weight_loss_kcal": 2305,
        "bmi": 24.7,
        "formula": "Mifflin-St Jeor",
        "notice": "仅供健康习惯参考，不是医疗建议",
    }


def test_profile_rejects_minor_and_client_owner_id():
    client = authenticated("alice")
    valid = {
        "birth_year": date.today().year - 30,
        "sex": "female",
        "height_cm": 165,
        "weight_kg": 55,
        "activity_level": "light",
    }
    assert client.put("/api/profile", json={**valid, "birth_year": date.today().year - 17}).status_code == 422
    assert client.put("/api/profile", json={**valid, "user_id": "someone-else"}).status_code == 422


def test_meal_crud_and_food_item_replacement():
    client = authenticated("alice")
    created = client.post(
        "/api/meals",
        json={
            "eaten_at": "2026-10-31T12:00:00+08:00",
            "meal_type": "lunch",
            "notes": "家常菜",
            "food_items": [
                {
                    "name": "米饭",
                    "quantity": 150,
                    "unit": "g",
                    "kcal": 174,
                    "protein_g": 3.9,
                    "carbs_g": 38,
                    "fat_g": 0.5,
                }
            ],
        },
    )
    assert created.status_code == 201
    meal_id = created.json()["id"]
    assert created.json()["status"] == "confirmed"
    assert len(client.get("/api/meals").json()) == 1

    patched = client.patch(
        f"/api/meals/{meal_id}",
        json={
            "notes": None,
            "food_items": [
                {
                    "name": "面条",
                    "quantity": 1,
                    "unit": "碗",
                    "kcal": 350,
                }
            ],
        },
    )
    assert patched.status_code == 200
    assert patched.json()["notes"] is None
    assert [item["name"] for item in patched.json()["food_items"]] == ["面条"]
    assert client.delete(f"/api/meals/{meal_id}").status_code == 204
    assert client.get(f"/api/meals/{meal_id}").status_code == 404


def test_exercise_crud_and_validation():
    client = authenticated("alice")
    invalid = client.post(
        "/api/exercises",
        json={
            "type": "散步",
            "started_at": "2026-10-31T18:00:00+08:00",
            "minutes": 0,
            "intensity": "low",
        },
    )
    assert invalid.status_code == 422

    created = client.post(
        "/api/exercises",
        json={
            "type": "散步",
            "started_at": "2026-10-31T18:00:00+08:00",
            "minutes": 30,
            "intensity": "low",
            "steps": 3500,
        },
    )
    exercise_id = created.json()["id"]
    assert created.status_code == 201
    assert client.patch(f"/api/exercises/{exercise_id}", json={"minutes": 45}).json()["minutes"] == 45
    assert client.delete(f"/api/exercises/{exercise_id}").status_code == 204


def test_sleep_cross_midnight_crud_and_range_validation():
    client = authenticated("alice")
    created = client.post(
        "/api/sleeps",
        json={
            "started_at": "2026-10-30T23:00:00+08:00",
            "ended_at": "2026-10-31T07:30:00+08:00",
            "quality": 4,
            "notes": "中途醒了一次",
        },
    )
    assert created.status_code == 201
    sleep_id = created.json()["id"]
    assert client.patch(f"/api/sleeps/{sleep_id}", json={"quality": 5}).status_code == 200
    assert (
        client.patch(
            f"/api/sleeps/{sleep_id}",
            json={"ended_at": "2026-11-02T07:30:00+08:00"},
        ).status_code
        == 422
    )
    assert client.delete(f"/api/sleeps/{sleep_id}").status_code == 204


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/meals",
            {
                "eaten_at": "2026-10-31T12:00:00",
                "meal_type": "lunch",
                "food_items": [{"name": "饭", "quantity": 1, "unit": "碗", "kcal": 300}],
            },
        ),
        (
            "/api/exercises",
            {
                "type": "散步",
                "started_at": "2026-10-31T18:00:00",
                "minutes": 30,
                "intensity": "low",
            },
        ),
    ],
)
def test_record_times_require_timezone(path, payload):
    client = authenticated("alice")
    assert client.post(path, json=payload).status_code == 422


def test_all_record_paths_hide_other_users_resources():
    alice = authenticated("alice")
    bob = authenticated("bob")
    timestamp = datetime.now(timezone.utc).isoformat()

    meal_id = bob.post(
        "/api/meals",
        json={
            "eaten_at": timestamp,
            "meal_type": "snack",
            "food_items": [{"name": "苹果", "quantity": 1, "unit": "个", "kcal": 80}],
        },
    ).json()["id"]
    exercise_id = bob.post(
        "/api/exercises",
        json={"type": "走路", "started_at": timestamp, "minutes": 20, "intensity": "low"},
    ).json()["id"]
    sleep_id = bob.post(
        "/api/sleeps",
        json={
            "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(),
            "quality": 4,
        },
    ).json()["id"]

    assert alice.get("/api/meals").json() == []
    assert alice.get("/api/exercises").json() == []
    assert alice.get("/api/sleeps").json() == []
    for path in (
        f"/api/meals/{meal_id}",
        f"/api/exercises/{exercise_id}",
        f"/api/sleeps/{sleep_id}",
    ):
        assert alice.get(path).status_code == 404
        assert alice.patch(path, json={"notes": "越权修改"}).status_code == 404
        assert alice.delete(path).status_code == 404

    assert bob.get(f"/api/meals/{meal_id}").status_code == 200
    assert bob.get(f"/api/exercises/{exercise_id}").status_code == 200
    assert bob.get(f"/api/sleeps/{sleep_id}").status_code == 200
