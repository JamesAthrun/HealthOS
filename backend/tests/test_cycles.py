import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

import pytest

from app.advice_service import (
    AdviceAction,
    AdviceContent,
    AdviceProviderError,
    build_advice_context,
    derive_cycle_observations,
    strip_cycle_mentions,
)
from app.audit import set_tenant_context
from app.cycle import PeriodSpan, summarize_cycles
from app.dashboard import DailySummary
from app.db import SessionLocal
from app.models import User
from tests.conftest import create_user, login, new_client


SETTINGS_ON = {"tracking_enabled": True, "share_with_ai": False, "adjust_targets": True}
SETTINGS_OFF = {**SETTINGS_ON, "tracking_enabled": False}


def authenticated(username: str, enable: bool = True, sex: str | None = "female"):
    create_user(username)
    client = new_client()
    assert login(client, username).status_code == 200
    if sex:
        assert client.put("/api/profile", json={"sex": sex}).status_code == 200
    if enable:
        assert client.put("/api/cycle-settings", json=SETTINGS_ON).status_code == 200
    return client


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def day(offset: int) -> str:
    return (today() - timedelta(days=offset)).isoformat()


def spans(*starts: str, length: int = 5) -> list[PeriodSpan]:
    result = []
    for value in starts:
        start = date.fromisoformat(value)
        result.append(PeriodSpan(start, start + timedelta(days=length - 1)))
    return result


# ---------- 算法 ----------


def test_no_data_and_insufficient_data_uses_28_days():
    empty = summarize_cycles([], date(2026, 3, 1))
    assert empty.has_data is False and empty.next_start is None

    one = summarize_cycles(spans("2026-03-01"), date(2026, 3, 10))
    assert one.insufficient_data is True
    assert one.avg_cycle_days == 28
    assert one.next_start == date(2026, 3, 29)
    assert one.next_start_earliest is None
    assert one.cycle_day == 10
    assert one.phase == "follicular"


def test_regular_cycles_phases_and_range():
    history = spans("2026-01-01", "2026-01-29", "2026-02-27", "2026-03-27")  # 28, 29, 28
    on = lambda d: summarize_cycles(history, date.fromisoformat(d))  # noqa: E731

    s = on("2026-03-28")
    assert s.avg_cycle_days == 28 and s.avg_period_days == 5
    assert s.insufficient_data is False
    assert s.next_start == date(2026, 4, 24)
    assert (s.next_start_earliest, s.next_start_latest) == (date(2026, 4, 24), date(2026, 4, 25))
    assert s.in_period is True and s.phase == "menstrual"
    assert on("2026-04-01").phase == "follicular"
    assert on("2026-04-10").phase == "ovulation"  # 4-24 − 14 = 4-10
    assert on("2026-04-15").phase == "luteal"
    assert on("2026-04-15").days_until_next == 9
    assert on("2026-04-15").alerts == []


def test_outliers_are_ignored():
    # 10 天和 90 天是异常值（漏记/误记），只用 30、30
    history = spans("2026-01-01", "2026-01-31", "2026-03-02", "2026-03-12", "2026-06-10")
    s = summarize_cycles(history, date(2026, 6, 12))
    assert s.avg_cycle_days == 30
    assert s.insufficient_data is False


def test_late_period():
    history = spans("2026-01-01", "2026-01-29", "2026-02-26")
    s = summarize_cycles(history, date(2026, 3, 30))
    assert s.phase == "late"
    assert s.late_days == 4
    assert s.days_until_next is None


def test_irregular_and_long_alerts():
    history = spans("2026-01-01", "2026-01-19", "2026-02-27", "2026-03-15")  # 18, 39, 16
    s = summarize_cycles(history, date(2026, 3, 20))
    assert any("短于 21 天或长于 35 天" in a for a in s.alerts)
    assert any("波动较大" in a for a in s.alerts)

    long_period = [PeriodSpan(date(2026, 3, 1), date(2026, 3, 9))]
    assert any("超过 7 天" in a for a in summarize_cycles(long_period, date(2026, 3, 12)).alerts)

    stale = summarize_cycles(spans("2026-01-01"), date(2026, 3, 10))
    assert any("超过 60 天" in a for a in stale.alerts)


def test_ongoing_period_and_cross_year():
    history = [*spans("2025-11-06", "2025-12-04"), PeriodSpan(date(2026, 1, 1), None)]  # 28, 28
    s = summarize_cycles(history, date(2026, 1, 3))
    assert s.in_period is True and s.phase == "menstrual"
    assert s.cycle_day == 3
    assert s.next_start == date(2026, 1, 29)


# ---------- 接口 ----------


def test_disabled_tracking_returns_404_and_settings_are_audited():
    client = authenticated("alice", enable=False)
    assert client.get("/api/cycle-settings").json() == {**SETTINGS_OFF, "available": True}
    for method, path in (("get", "/api/cycles"), ("get", "/api/cycles/summary"), ("post", "/api/cycles/start-today")):
        assert getattr(client, method)(path).status_code == 404

    client.put("/api/cycle-settings", json=SETTINGS_ON)
    created = client.post("/api/cycles", json={"start_date": day(3), "symptoms": ["cramps", "cramps"]})
    assert created.status_code == 201
    assert created.json()["symptoms"] == ["cramps"]

    # 关闭后隐藏但不删除
    client.put("/api/cycle-settings", json=SETTINGS_OFF)
    assert client.get("/api/cycles").status_code == 404
    client.put("/api/cycle-settings", json=SETTINGS_ON)
    assert len(client.get("/api/cycles").json()) == 1

    events = [e["event_type"] for e in client.get("/api/me/audit-events").json()]
    assert "cycle_tracking_enabled" in events and "cycle_tracking_disabled" in events


def test_validation_rules():
    client = authenticated("alice")
    post = lambda **body: client.post("/api/cycles", json=body)  # noqa: E731
    assert post(start_date=day(-1)).status_code == 422
    assert post(start_date=day(5), end_date=day(6)).status_code == 422
    assert post(start_date=day(30), end_date=day(10)).status_code == 422  # 21 天
    assert post(start_date=day(5), flow="huge").status_code == 422
    assert post(start_date=day(5), symptoms=["sneeze"]).status_code == 422

    assert post(start_date=day(40), end_date=day(36)).status_code == 201
    assert post(start_date=day(38), end_date=day(35)).status_code == 409  # 重叠
    assert post(start_date=day(10)).status_code == 201  # 未结束
    assert post(start_date=day(3)).status_code == 409  # 第二条未结束
    assert post(start_date=day(20), end_date=day(18)).status_code == 201  # 补录更早的
    assert client.post("/api/cycles/start-today").status_code == 409

    ended = client.post("/api/cycles/end-today")
    assert ended.status_code == 200
    assert ended.json()["end_date"] == day(0)
    assert client.post("/api/cycles/end-today").status_code == 409

    first = client.get("/api/cycles").json()[-1]
    assert first["start_date"] == day(40)
    assert client.patch(f"/api/cycles/{first['id']}", json={"end_date": day(41)}).status_code == 422
    # 改成未结束会与之后的记录重叠
    assert client.patch(f"/api/cycles/{first['id']}", json={"end_date": None}).status_code == 409
    patched = client.patch(f"/api/cycles/{first['id']}", json={"flow": "heavy", "symptoms": ["fatigue"]})
    assert patched.json()["flow"] == "heavy" and patched.json()["symptoms"] == ["fatigue"]


def test_cycles_are_isolated_and_delete_all():
    alice = authenticated("alice")
    bob = authenticated("bob")
    period = alice.post("/api/cycles", json={"start_date": day(5), "end_date": day(1)}).json()
    assert bob.get(f"/api/cycles/{period['id']}").status_code == 404
    assert bob.patch(f"/api/cycles/{period['id']}", json={"notes": "x"}).status_code == 404
    assert bob.delete(f"/api/cycles/{period['id']}").status_code == 404
    assert bob.get("/api/cycles").json() == []
    assert bob.get("/api/cycles/summary").json()["has_data"] is False
    # bob 删除全部只影响自己
    assert bob.delete("/api/cycles").status_code == 204
    assert len(alice.get("/api/cycles").json()) == 1

    summary = alice.get("/api/cycles/summary").json()
    assert summary["cycle_day"] == 6 and summary["insufficient_data"] is True
    assert "不能用于避孕" in summary["notice"]
    assert alice.delete("/api/cycles").status_code == 204
    assert alice.get("/api/cycles").json() == []


def test_only_female_profile_can_enable():
    for username, sex in (("dave", None), ("erin", "male")):
        client = authenticated(username, enable=False, sex=sex)
        assert client.get("/api/cycle-settings").json()["available"] is False
        assert client.put("/api/cycle-settings", json=SETTINGS_ON).status_code == 422
        # 关闭总是允许
        assert client.put("/api/cycle-settings", json=SETTINGS_OFF).status_code == 200

    # 开启后把性别改成男：入口关闭但数据保留
    client = authenticated("carol")
    client.post("/api/cycles", json={"start_date": day(3)})
    client.put("/api/profile", json={"sex": "male"})
    assert client.get("/api/cycles").status_code == 404
    client.put("/api/profile", json={"sex": "female"})
    assert len(client.get("/api/cycles").json()) == 1


def test_summary_adjustments_follow_phase_and_switch():
    client = authenticated("alice")
    # 经期中：补铁提示，不加热量
    client.post("/api/cycles", json={"start_date": day(1)})
    s = client.get("/api/cycles/summary").json()
    assert s["phase"] == "menstrual" and s["kcal_bonus"] == 0
    assert any("补铁" in tip for tip in s["tips"])

    # 经前：28 天周期第 20 天 → +150
    client.delete("/api/cycles")
    client.post("/api/cycles", json={"start_date": day(19), "end_date": day(15)})
    s = client.get("/api/cycles/summary").json()
    assert s["phase"] == "luteal" and s["kcal_bonus"] == 150 and s["tips"]

    client.put("/api/cycle-settings", json={**SETTINGS_ON, "adjust_targets": False})
    s = client.get("/api/cycles/summary").json()
    assert s["phase"] == "luteal" and s["kcal_bonus"] == 0 and s["tips"] == []
    events = [e["event_type"] for e in client.get("/api/me/audit-events").json()]
    assert "cycle_adjust_disabled" in events


# ---------- 周期与建议 ----------


def _advice_context(username: str):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        set_tenant_context(db, user.id)
        return build_advice_context(db, user, kind="daily", for_date=today())


def test_advice_context_has_no_cycle_data_without_sharing():
    client = authenticated("alice")
    client.post("/api/cycles", json={"start_date": day(1), "symptoms": ["cramps"]})
    context, observations = _advice_context("alice")
    assert "cycle" not in context
    assert all(item.kind != "cycle" for item in observations)
    dumped = json.dumps(context, ensure_ascii=False)
    for word in ("phase", "cramps", "menstrual", "latest_period"):
        assert word not in dumped


def test_advice_context_includes_cycle_layer_when_shared():
    client = authenticated("alice")
    client.post("/api/cycles", json={"start_date": day(1), "symptoms": ["cramps"]})
    client.put("/api/cycle-settings", json={**SETTINGS_ON, "share_with_ai": True})
    events = [e["event_type"] for e in client.get("/api/me/audit-events").json()]
    assert "cycle_ai_share_enabled" in events

    context, observations = _advice_context("alice")
    cycle = context["cycle"]
    assert cycle["phase"] == "menstrual" and cycle["cycle_day"] == 2
    assert cycle["latest_period_symptoms"] == ["cramps"]
    assert day(1) not in json.dumps(cycle)  # 不发送具体日期
    assert "cycle-early-period-discomfort" in [item.id for item in observations]

    # 关闭周期记录后同样不再发送
    client.put("/api/cycle-settings", json={**SETTINGS_OFF, "share_with_ai": True})
    assert "cycle" not in _advice_context("alice")[0]


def test_cycle_mentions_are_removed_when_not_shared():
    action = AdviceAction(category="general", action="早点睡。", rationale="资料有限。", confidence="low")
    content = AdviceContent(summary="先从小事开始。", actions=[action], limitations=["无生理周期数据。", "睡眠记录少。"])
    assert strip_cycle_mentions(content, {}).limitations == ["睡眠记录少。"]
    assert strip_cycle_mentions(content, {"cycle": {}}).limitations == content.limitations
    in_body = content.model_copy(update={"summary": "经期注意休息。"})
    with pytest.raises(AdviceProviderError, match="AI_UNSHARED_CYCLE"):
        strip_cycle_mentions(in_body, {})


def test_luteal_appetite_observation():
    days = [
        DailySummary.model_validate({
            "date": today() - timedelta(days=offset), "kcal": 2300, "protein_g": 0, "carbs_g": 0,
            "fat_g": 0, "meal_count": 3, "exercise_minutes": 0, "steps": 0, "sleep_minutes": 0,
            "sleep_quality": None,
        })
        for offset in (3, 2, 1)
    ]
    luteal = {"phase": "luteal", "cycle_day": 20, "latest_period_symptoms": []}
    assert [o.id for o in derive_cycle_observations(luteal, days, 2000)] == ["cycle-luteal-appetite"]
    assert derive_cycle_observations(luteal, days, 2500) == []
    assert derive_cycle_observations({**luteal, "phase": "follicular"}, days, 2000) == []
    assert derive_cycle_observations(None, days, 2000) == []
