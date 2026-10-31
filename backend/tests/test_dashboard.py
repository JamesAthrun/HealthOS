from datetime import date

from tests.conftest import create_user, login, new_client


def authenticated(username: str):
    create_user(username)
    client = new_client()
    assert login(client, username).status_code == 200
    return client


def add_day(client, day: str) -> None:
    assert (
        client.post(
            "/api/meals",
            json={
                "eaten_at": f"{day}T12:00:00+08:00",
                "meal_type": "lunch",
                "food_items": [
                    {
                        "name": "测试套餐",
                        "quantity": 1,
                        "unit": "份",
                        "kcal": 520,
                        "protein_g": 25,
                        "carbs_g": 60,
                        "fat_g": 18,
                    }
                ],
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/exercises",
            json={
                "type": "散步",
                "started_at": f"{day}T18:00:00+08:00",
                "minutes": 35,
                "intensity": "low",
                "steps": 4200,
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/sleeps",
            json={
                "started_at": "2026-10-30T23:00:00+08:00",
                "ended_at": f"{day}T07:30:00+08:00",
                "quality": 4,
            },
        ).status_code
        == 201
    )


def test_today_dashboard_aggregates_confirmed_records():
    client = authenticated("alice")
    client.put(
        "/api/profile",
        json={
            "birth_year": date.today().year - 30,
            "sex": "female",
            "height_cm": 165,
            "weight_kg": 55,
            "activity_level": "light",
            "daily_kcal_target": 2000,
        },
    )
    add_day(client, "2026-10-31")

    response = client.get("/api/dashboard/today?on=2026-10-31")
    assert response.status_code == 200
    assert response.json() == {
        "date": "2026-10-31",
        "target_kcal": 2000,
        "kcal_completion_percent": 26,
        "summary": {
            "date": "2026-10-31",
            "kcal": 520.0,
            "protein_g": 25.0,
            "carbs_g": 60.0,
            "fat_g": 18.0,
            "meal_count": 1,
            "exercise_minutes": 35,
            "steps": 4200,
            "sleep_minutes": 510,
            "sleep_quality": 4.0,
        },
    }


def test_trends_fill_empty_days_and_exclude_other_users():
    alice = authenticated("alice")
    bob = authenticated("bob")
    add_day(alice, "2026-10-31")
    bob.post(
        "/api/meals",
        json={
            "eaten_at": "2026-10-30T12:00:00+08:00",
            "meal_type": "lunch",
            "food_items": [
                {"name": "别人的饭", "quantity": 1, "unit": "份", "kcal": 999}
            ],
        },
    )

    response = alice.get("/api/dashboard/trends?to=2026-10-31&days=3")
    assert response.status_code == 200
    body = response.json()
    assert body["from_date"] == "2026-10-29"
    assert body["to_date"] == "2026-10-31"
    assert [item["kcal"] for item in body["days"]] == [0.0, 0.0, 520.0]
    assert [item["date"] for item in body["days"]] == [
        "2026-10-29",
        "2026-10-30",
        "2026-10-31",
    ]


def test_dashboard_uses_account_timezone_at_utc_boundary():
    client = authenticated("alice")
    created = client.post(
        "/api/meals",
        json={
            "eaten_at": "2026-10-30T16:30:00+00:00",
            "meal_type": "breakfast",
            "food_items": [
                {"name": "凌晨加餐", "quantity": 1, "unit": "份", "kcal": 100}
            ],
        },
    )
    assert created.status_code == 201
    assert client.get("/api/dashboard/today?on=2026-10-30").json()["summary"]["kcal"] == 0
    assert client.get("/api/dashboard/today?on=2026-10-31").json()["summary"]["kcal"] == 100
