from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.advice_service import derive_weight_observations
from app.weights import WeightPoint, change_over, trend_points
from tests.conftest import create_user, login, new_client


def authenticated(username: str):
    create_user(username)
    client = new_client()
    assert login(client, username).status_code == 200
    return client


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def day(offset: int) -> str:
    return (today() - timedelta(days=offset)).isoformat()


def test_same_day_overwrites_and_profile_follows_latest():
    client = authenticated("alice")
    first = client.post("/api/weights", json={"measured_on": day(10), "weight_kg": 70})
    assert first.status_code == 201
    replaced = client.post("/api/weights", json={"measured_on": day(10), "weight_kg": 69.5, "waist_cm": 80})
    assert replaced.status_code == 200
    assert replaced.json()["id"] == first.json()["id"]
    assert len(client.get("/api/weights").json()) == 1

    latest = client.post("/api/weights", json={"measured_on": day(0), "weight_kg": 68.8})
    assert client.get("/api/profile").json()["weight_kg"] == 68.8

    # 删除最新一条后，档案体重回退到上一条
    assert client.delete(f"/api/weights/{latest.json()['id']}").status_code == 204
    assert client.get("/api/profile").json()["weight_kg"] == 69.5


def test_validation_future_date_and_date_clash():
    client = authenticated("alice")
    assert client.post("/api/weights", json={"measured_on": day(-1), "weight_kg": 70}).status_code == 422
    assert client.post("/api/weights", json={"measured_on": day(0), "weight_kg": 10}).status_code == 422
    assert client.post("/api/weights", json={"measured_on": day(0), "weight_kg": 70, "body_fat_pct": 90}).status_code == 422

    a = client.post("/api/weights", json={"measured_on": day(1), "weight_kg": 70}).json()
    client.post("/api/weights", json={"measured_on": day(2), "weight_kg": 70.2})
    assert client.patch(f"/api/weights/{a['id']}", json={"measured_on": day(2)}).status_code == 409
    assert client.patch(f"/api/weights/{a['id']}", json={"measured_on": day(-1)}).status_code == 422
    assert client.patch(f"/api/weights/{a['id']}", json={"weight_kg": None}).status_code == 422
    assert client.patch(f"/api/weights/{a['id']}", json={"weight_kg": 69.9}).json()["weight_kg"] == 69.9


def test_suspicious_jump_is_saved_with_warning():
    client = authenticated("alice")
    client.post("/api/weights", json={"measured_on": day(1), "weight_kg": 70})
    jumped = client.post("/api/weights", json={"measured_on": day(0), "weight_kg": 76})
    assert jumped.status_code == 201
    assert "请确认是否输错" in jumped.json()["warning"]
    normal = client.post("/api/weights", json={"measured_on": day(0), "weight_kg": 70.4})
    assert normal.json()["warning"] is None


def test_weights_are_isolated_between_users():
    alice = authenticated("alice")
    bob = authenticated("bob")
    log = alice.post("/api/weights", json={"measured_on": day(0), "weight_kg": 60}).json()
    assert bob.get(f"/api/weights/{log['id']}").status_code == 404
    assert bob.patch(f"/api/weights/{log['id']}", json={"weight_kg": 99}).status_code == 404
    assert bob.delete(f"/api/weights/{log['id']}").status_code == 404
    assert bob.get("/api/weights").json() == []
    assert bob.get("/api/weights/summary").json()["current"] is None
    assert alice.get(f"/api/weights/{log['id']}").json()["weight_kg"] == 60


def test_summary_initial_current_target_bmi_and_trend():
    client = authenticated("alice")
    client.put(
        "/api/profile",
        json={"height_cm": 170, "target_weight_kg": 65, "sex": "female"},
    )
    for offset, weight in [(40, 72.0), (8, 70.0), (3, 69.6), (0, 69.0)]:
        client.post("/api/weights", json={"measured_on": day(offset), "weight_kg": weight})

    summary = client.get("/api/weights/summary").json()
    assert summary["initial"] == {"date": day(40), "weight_kg": 72.0}
    assert summary["current"] == {"date": day(0), "weight_kg": 69.0}
    assert summary["change_kg"] == -3.0
    assert summary["to_target_kg"] == 4.0
    assert summary["change_7d_kg"] == -1.0  # 基准是 7 天前或之前最近的一条（8 天前 70.0）
    assert summary["change_30d_kg"] == -3.0
    assert summary["bmi"] == 23.9
    # 趋势只含最近 30 天；7 天移动平均覆盖窗口内已有记录
    assert [p["date"] for p in summary["trend"]] == [day(8), day(3), day(0)]
    assert summary["trend"][-1]["avg_7d_kg"] == 69.3


def test_change_over_handles_sparse_data():
    t = date(2026, 1, 10)
    points = [WeightPoint(date=date(2026, 1, 9), weight_kg=70)]
    assert change_over(points, t, 7) is None
    # 窗口起点之前没有记录时，用窗口内最早的一条
    points = [WeightPoint(date=date(2026, 1, 6), weight_kg=70), WeightPoint(date=date(2026, 1, 10), weight_kg=69.2)]
    assert change_over(points, t, 7) == -0.8
    # 最新记录太旧时不计算
    old = [WeightPoint(date=date(2025, 12, 1), weight_kg=70), WeightPoint(date=date(2025, 12, 2), weight_kg=69)]
    assert change_over(old, t, 7) is None
    # 基准不会取得过于久远（超过两个窗口）
    far = [WeightPoint(date=date(2025, 10, 1), weight_kg=80), WeightPoint(date=date(2026, 1, 9), weight_kg=70)]
    assert change_over(far, t, 7) is None
    assert trend_points([], t) == []


def test_profile_weight_is_recorded_as_todays_log_and_not_wiped():
    client = authenticated("alice")
    base = {"birth_year": today().year - 30, "sex": "male", "height_cm": 180, "activity_level": "light"}
    client.put("/api/profile", json={**base, "weight_kg": 80})
    logs = client.get("/api/weights").json()
    assert [(log["measured_on"], log["weight_kg"]) for log in logs] == [(day(0), 80)]

    # 新客户端不再传 weight_kg，不会把体重清空
    saved = client.put("/api/profile", json={**base, "target_weight_kg": 75})
    assert saved.json()["weight_kg"] == 80
    assert saved.json()["target_weight_kg"] == 75
    assert client.get("/api/profile/kcal-reference").status_code == 200


def test_weight_observations():
    assert derive_weight_observations(None, None) == []
    ids = [o.id for o in derive_weight_observations(-1.4, 2.5)]
    assert ids == ["weight-drop-fast-7d", "weight-gain-30d"]
    assert derive_weight_observations(-0.8, 1.0) == []


def test_migration_copies_existing_profile_weight():
    import uuid

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    from app.db import engine
    from tests.conftest import BACKEND_DIR

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.downgrade(cfg, "0006")
    try:
        with_weight, without_weight = uuid.uuid4(), uuid.uuid4()
        with engine.begin() as conn:
            for uid, name, weight in [(with_weight, "w1", 66.5), (without_weight, "w2", None)]:
                conn.execute(
                    text(
                        "INSERT INTO users (id, username, password_hash, display_name, is_admin, timezone, locale, failed_login_count) "
                        "VALUES (:id, :name, 'x', :name, false, 'Asia/Shanghai', 'zh-CN', 0)"
                    ),
                    {"id": uid.hex if engine.dialect.name == "sqlite" else uid, "name": name},
                )
                if engine.dialect.name == "postgresql":
                    conn.execute(text("SELECT set_config('app.current_user_id', :u, true)"), {"u": str(uid)})
                conn.execute(
                    text(
                        "INSERT INTO profiles (user_id, weight_kg, updated_at) "
                        "VALUES (:id, :w, '2026-10-01 20:00:00+00:00')"
                    ),
                    {"id": uid.hex if engine.dialect.name == "sqlite" else uid, "w": weight},
                )
    finally:
        command.upgrade(cfg, "head")

    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT set_config('app.current_user_id', :u, true)"), {"u": str(with_weight)})
        rows = conn.execute(text("SELECT measured_on, weight_kg FROM weight_logs")).all()
    # 20:00 UTC 是上海时间次日 04:00，所以日期是 10-02；没有体重的档案不生成记录
    assert [(str(r[0]), r[1]) for r in rows] == [("2026-10-02", 66.5)]
