from datetime import date

from tests.conftest import create_user, login, new_client


def authenticated(username: str):
    create_user(username)
    client = new_client()
    assert login(client, username).status_code == 200
    return client


def test_targets_default_empty_then_saved_and_cleared():
    client = authenticated("alice")
    empty = client.get("/api/nutrition-targets")
    assert empty.status_code == 200
    assert all(value is None for value in empty.json().values())

    body = {"daily_kcal_target": 1800, "protein_g": 90, "carbs_g": None, "fat_g": None,
            "fiber_g": 30, "sugar_max_g": 25, "sodium_max_mg": 1500}
    saved = client.put("/api/nutrition-targets", json=body)
    assert saved.status_code == 200
    assert saved.json() == body
    assert client.get("/api/profile").json()["daily_kcal_target"] == 1800

    cleared = client.put("/api/nutrition-targets", json={})
    assert all(value is None for value in cleared.json().values())


def test_targets_validation_and_isolation():
    alice = authenticated("alice")
    bob = authenticated("bob")
    assert alice.put("/api/nutrition-targets", json={"sodium_max_mg": 50}).status_code == 422
    assert alice.put("/api/nutrition-targets", json={"daily_kcal_target": 500}).status_code == 422
    assert alice.put("/api/nutrition-targets", json={"iron_mg": 18}).status_code == 422
    alice.put("/api/nutrition-targets", json={"protein_g": 100})
    assert bob.get("/api/nutrition-targets").json()["protein_g"] is None


def test_saving_profile_without_kcal_target_keeps_it():
    client = authenticated("alice")
    client.put("/api/nutrition-targets", json={"daily_kcal_target": 1900})
    profile = {
        "birth_year": date.today().year - 30,
        "sex": "female",
        "height_cm": 165,
        "activity_level": "light",
    }
    assert client.put("/api/profile", json=profile).status_code == 200
    assert client.get("/api/nutrition-targets").json()["daily_kcal_target"] == 1900
    # 旧客户端显式传了这个字段时仍然生效
    client.put("/api/profile", json={**profile, "daily_kcal_target": 2000})
    assert client.get("/api/nutrition-targets").json()["daily_kcal_target"] == 2000
