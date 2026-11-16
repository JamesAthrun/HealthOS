from app.config import get_settings
from tests.conftest import create_user, login, new_client
from tests.test_meal_photos import image_bytes, upload

MEAL = {
    "eaten_at": "2026-11-16T12:00:00+08:00",
    "meal_type": "lunch",
    "notes": "ç§äººå¤‡æ³¨",
    "food_items": [
        {"name": "ç«é”…", "quantity": 1, "unit": "é”…", "kcal": 2000, "protein_g": 100, "carbs_g": 80, "fat_g": 120, "sodium_mg": 6000}
    ],
}


def _client(username: str):
    create_user(username, display_name=username.title())
    client = new_client()
    assert login(client, username).status_code == 200
    return client


def _friends(a, b, b_name="bob"):
    assert a.post("/api/friends/requests", json={"username": b_name}).json() == {"status": "pending"}
    request_id = b.get("/api/messages").json()["items"][0]["id"]
    assert b.post(f"/api/friends/requests/{request_id}/accept").status_code == 204
    return a.get("/api/friends").json()[0]["user"]["id"]


def _incoming_share(client):
    return next(m for m in client.get("/api/messages").json()["items"] if m["kind"] == "meal_share")


def test_friend_request_flow_and_errors():
    alice, bob = _client("alice"), _client("bob")
    assert alice.post("/api/friends/requests", json={"username": "nobody"}).status_code == 404
    assert alice.post("/api/friends/requests", json={"username": "alice"}).status_code == 400
    assert alice.post("/api/friends/requests", json={"username": "Bob"}).status_code == 201
    assert alice.post("/api/friends/requests", json={"username": "bob"}).status_code == 409

    assert bob.get("/api/messages/unread-count").json() == {"unread": 1}
    message = bob.get("/api/messages").json()["items"][0]
    assert message["kind"] == "friend_request" and message["direction"] == "in"
    assert message["other"]["display_name"] == "Alice"
    # åªæœ‰æŽ¥æ”¶æ–¹èƒ½å¤„ç†
    assert alice.post(f"/api/friends/requests/{message['id']}/accept").status_code == 404
    assert bob.post(f"/api/friends/requests/{message['id']}/decline").status_code == 204
    assert alice.get("/api/friends").json() == []

    # è¢«æ‹’ç»åŽå¯ä»¥é‡å‘ï¼›å¯¹æ–¹åå‘å‘è¯·æ±‚åˆ™ç›´æŽ¥æˆä¸ºå¥½å‹
    assert alice.post("/api/friends/requests", json={"username": "bob"}).status_code == 201
    assert bob.post("/api/friends/requests", json={"username": "alice"}).json() == {"status": "accepted"}
    assert [f["user"]["username"] for f in alice.get("/api/friends").json()] == ["bob"]
    assert bob.get("/api/messages/unread-count").json() == {"unread": 0}
    assert alice.post("/api/friends/requests", json={"username": "bob"}).status_code == 409


def test_strangers_see_nothing_and_cannot_share():
    alice, bob, carol = _client("alice"), _client("bob"), _client("carol")
    bob_id = _friends(alice, bob)
    meal = alice.post("/api/meals", json=MEAL).json()
    carol_id = carol.get("/api/me").json()["id"]
    assert alice.post(f"/api/meals/{meal['id']}/shares", json={"friend_ids": [carol_id], "ratio": 0.5}).status_code == 404
    assert alice.post(f"/api/meals/{meal['id']}/shares", json={"friend_ids": [bob_id], "ratio": 0.5}).status_code == 201
    share_id = _incoming_share(bob)["id"]
    assert carol.get("/api/messages").json()["items"] == []
    assert carol.post(f"/api/meal-shares/{share_id}/decline").status_code == 404
    assert carol.get(f"/api/meal-shares/{share_id}/photos/0").status_code == 404
    # bob ä¸èƒ½åˆ†äº« alice çš„è®°å½•
    assert bob.post(f"/api/meals/{meal['id']}/shares", json={"friend_ids": [bob_id], "ratio": 0.5}).status_code == 404


def test_share_accept_copies_photos_and_scales_own_portion():
    alice, bob = _client("alice"), _client("bob")
    bob_id = _friends(alice, bob)
    photo_id = upload(alice, image_bytes("red")).json()["id"]
    meal = alice.post("/api/meals", json={**MEAL, "photo_ids": [photo_id]}).json()

    result = alice.post(
        f"/api/meals/{meal['id']}/shares", json={"friend_ids": [bob_id], "ratio": 0.5, "my_ratio": 0.5}
    ).json()
    assert result["shared"] == 1
    assert result["meal"]["food_items"][0]["kcal"] == 1000
    # é‡å¤åˆ†äº«ç»™åŒä¸€äººä¸ä¼šå†å‘
    again = alice.post(f"/api/meals/{meal['id']}/shares", json={"friend_ids": [bob_id], "ratio": 0.5}).json()
    assert again["shared"] == 0

    message = _incoming_share(bob)
    share = message["share"]
    assert message["status"] == "pending" and share["photo_count"] == 1
    assert share["food_items"][0]["kcal"] == 2000  # å¿«ç…§æ˜¯æ•´é¤
    assert "notes" not in share
    thumb = bob.get(f"/api/meal-shares/{message['id']}/photos/0?size=thumb")
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"

    item = {**share["food_items"][0], "kcal": 1000, "quantity": 0.5}
    created = bob.post(
        f"/api/meal-shares/{message['id']}/accept",
        json={"ratio": 0.5, "eaten_at": share["eaten_at"], "meal_type": "lunch", "food_items": [item]},
    )
    assert created.status_code == 201
    bob_meal = created.json()
    assert bob_meal["shared_from"] == "Alice"
    assert len(bob_meal["photo_ids"]) == 1 and bob_meal["photo_ids"][0] != photo_id
    assert bob.get(f"/api/meal-photos/{bob_meal['photo_ids'][0]}").status_code == 200
    # é‚€è¯·é‡Œçš„ç…§ç‰‡å‰¯æœ¬å·²è½¬èµ°
    assert not (get_settings().photo_dir / "shares" / message["id"]).exists()
    assert bob.post(f"/api/meal-shares/{message['id']}/decline").status_code == 409

    outgoing = _incoming_share(alice)
    assert outgoing["direction"] == "out" and outgoing["status"] == "accepted"


def test_sender_edit_prompts_receiver_to_sync():
    alice, bob = _client("alice"), _client("bob")
    bob_id = _friends(alice, bob)
    meal = alice.post("/api/meals", json=MEAL).json()
    alice.post(f"/api/meals/{meal['id']}/shares", json={"friend_ids": [bob_id], "ratio": 0.5, "my_ratio": 0.5})
    message = _incoming_share(bob)
    share = message["share"]
    bob_meal = bob.post(
        f"/api/meal-shares/{message['id']}/accept",
        json={"ratio": 0.5, "eaten_at": share["eaten_at"], "meal_type": "lunch", "food_items": share["food_items"]},
    ).json()
    assert bob.post(f"/api/meal-shares/{message['id']}/sync", json={"apply": True}).status_code == 409

    # alice åªæ”¹å¤‡æ³¨ä¸ä¼šé€šçŸ¥
    alice.patch(f"/api/meals/{meal['id']}", json={"notes": "æ”¹å¤‡æ³¨"})
    assert bob.get("/api/messages/unread-count").json() == {"unread": 0}

    # alice æŠŠè‡ªå·±é‚£ä¸€åŠæ”¹æˆ 1200 kcal â†’ æ•´é¤ 2400ï¼Œbob çš„ä¸€åŠ 1200
    item = {**MEAL["food_items"][0], "kcal": 1200}
    alice.patch(f"/api/meals/{meal['id']}", json={"food_items": [item], "meal_type": "dinner"})
    assert bob.get("/api/messages/unread-count").json() == {"unread": 1}
    updated = _incoming_share(bob)
    assert updated["share"]["update_pending"] is True
    assert updated["share"]["food_items"][0]["kcal"] == 2400

    assert bob.post(f"/api/meal-shares/{message['id']}/sync", json={"apply": True}).status_code == 204
    synced = bob.get(f"/api/meals/{bob_meal['id']}").json()
    assert synced["meal_type"] == "dinner"
    assert synced["food_items"][0]["kcal"] == 1200
    assert bob.get("/api/messages/unread-count").json() == {"unread": 0}


def test_decline_cancel_and_unfriend_clean_up_photos():
    alice, bob = _client("alice"), _client("bob")
    bob_id = _friends(alice, bob)
    photo_id = upload(alice, image_bytes("blue")).json()["id"]
    meal = alice.post("/api/meals", json={**MEAL, "photo_ids": [photo_id]}).json()
    shares_dir = get_settings().photo_dir / "shares"

    alice.post(f"/api/meals/{meal['id']}/shares", json={"friend_ids": [bob_id], "ratio": 0.5})
    first = _incoming_share(bob)["id"]
    assert (shares_dir / first / "0.jpg").is_file()
    assert bob.post(f"/api/meal-shares/{first}/decline").status_code == 204
    assert not (shares_dir / first).exists()

    alice.post(f"/api/meals/{meal['id']}/shares", json={"friend_ids": [bob_id], "ratio": 0.5})
    second = _incoming_share(bob)["id"]
    assert bob.post(f"/api/meal-shares/{second}/cancel").status_code == 404  # åªæœ‰å‘é€æ–¹èƒ½æ’¤å›ž
    assert alice.post(f"/api/meal-shares/{second}/cancel").status_code == 204
    assert not (shares_dir / second).exists()

    alice.post(f"/api/meals/{meal['id']}/shares", json={"friend_ids": [bob_id], "ratio": 0.5})
    third = _incoming_share(bob)["id"]
    assert bob.delete(f"/api/friends/{alice.get('/api/me').json()['id']}").status_code == 204
    assert alice.get("/api/friends").json() == []
    assert not (shares_dir / third).exists()
    assert _incoming_share(bob)["status"] == "cancelled"
