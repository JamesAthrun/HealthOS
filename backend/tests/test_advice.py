import json
import uuid
from datetime import date, datetime, time, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app import advice_service
from app.advice_service import (
    AdviceAction,
    AdviceContent,
    AdviceProviderError,
    ProviderResult,
    _validate_plan_timing,
    _validate_safety,
    build_advice_context,
    derive_observations,
    generate_advice,
)
from app.config import Settings, get_settings
from app.dashboard import DailySummary
from app.db import SessionLocal, engine
from app.audit import commit_with_tenant_context, set_tenant_context
from app.models import Advice, User, UserNote
from tests.conftest import create_user, login, new_client


def _day(day: int | date, **overrides: object) -> DailySummary:
    values: dict[str, object] = {
        "date": day if isinstance(day, date) else date(2026, 10, day),
        "kcal": 0,
        "protein_g": 0,
        "carbs_g": 0,
        "fat_g": 0,
        "meal_count": 0,
        "exercise_minutes": 0,
        "steps": 0,
        "sleep_minutes": 0,
        "sleep_quality": None,
    }
    values.update(overrides)
    return DailySummary.model_validate(values)


def _generated() -> ProviderResult:
    return ProviderResult(
        content=AdviceContent(
            summary="根据已有记录，先从一个小行动开始。",
            actions=[
                AdviceAction(
                    category="exercise",
                    action="明天安排一次 15 分钟轻松散步。",
                    rationale="最近三天没有运动记录。",
                    evidence_refs=["exercise-none-3d"],
                    confidence="medium",
                )
            ],
            limitations=["饮食记录较少；这是健康习惯参考，不是医疗建议。"],
        ),
        latency_ms=20,
        prompt_tokens=100,
        completion_tokens=80,
    )


def test_observations_are_deterministic() -> None:
    days = [
        _day(24 + index, kcal=1200, meal_count=3, sleep_minutes=330)
        for index in range(7)
    ]
    observations = derive_observations(days, target_kcal=2000)
    assert [item.id for item in observations] == [
        "kcal-below-target-3d",
        "exercise-none-3d",
        "sleep-under-6h-3d",
    ]


def test_kcal_trend_requires_three_consecutive_recorded_days() -> None:
    days = [_day(24 + index, kcal=1200, meal_count=3) for index in range(7)]
    days[-2] = _day(29)

    observation_ids = {item.id for item in derive_observations(days, target_kcal=2000)}

    assert "kcal-below-target-3d" not in observation_ids


def test_partial_current_day_does_not_create_completed_day_trends() -> None:
    today = date.today()
    days = [
        _day(today - timedelta(days=2), kcal=1200, meal_count=3),
        _day(today - timedelta(days=1), kcal=1200, meal_count=3),
        _day(today, kcal=300, meal_count=1),
    ]

    observation_ids = {
        item.id
        for item in derive_observations(days, target_kcal=2000, current_date=today)
    }

    assert "kcal-below-target-3d" not in observation_ids
    assert "exercise-none-3d" not in observation_ids


def test_notes_crud_defaults_temporary_expiry_and_isolates_users() -> None:
    create_user("alice")
    create_user("bob")
    alice = new_client()
    login(alice, "alice")

    created = alice.post(
        "/api/notes", json={"content": "这周膝盖不适", "category": "temporary"}
    )
    assert created.status_code == 201
    note = created.json()
    assert note["expires_at"] is not None
    assert alice.patch(
        f"/api/notes/{note['id']}",
        json={"content": "晚饭后不安排跑步", "category": "limitation"},
    ).json()["expires_at"] is None

    bob = new_client()
    login(bob, "bob")
    assert bob.patch(f"/api/notes/{note['id']}", json={"content": "篡改"}).status_code == 404
    assert bob.delete(f"/api/notes/{note['id']}").status_code == 404
    assert bob.get("/api/notes").json() == []

    assert alice.delete(f"/api/notes/{note['id']}").status_code == 204
    assert alice.get("/api/notes").json() == []


def test_note_expiry_requires_timezone_and_future_value() -> None:
    create_user("alice")
    client = new_client()
    login(client, "alice")

    naive = client.post(
        "/api/notes",
        json={
            "content": "下周出差",
            "category": "temporary",
            "expires_at": "2099-01-01T10:00:00",
        },
    )
    assert naive.status_code == 422

    note_id = client.post(
        "/api/notes", json={"content": "下周出差", "category": "temporary"}
    ).json()["id"]
    assert client.patch(
        f"/api/notes/{note_id}", json={"expires_at": "2020-01-01T10:00:00+08:00"}
    ).status_code == 422


def test_planning_consent_is_separate_and_advice_flow(monkeypatch) -> None:
    alice = create_user("alice")
    client = new_client()
    login(client, "alice")

    assert client.get("/api/planning-consent").json()["granted"] is False
    assert client.get("/api/ai-consent").json()["granted"] is False
    assert client.post("/api/advice/daily", json={}).status_code == 403
    assert client.put("/api/planning-consent").json()["granted"] is True
    assert client.get("/api/ai-consent").json()["granted"] is False

    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test")
    monkeypatch.setattr(advice_service, "generate_advice", lambda _context, _settings: _generated())
    response = client.post("/api/advice/daily", json={"for_date": "2026-11-02"})
    assert response.status_code == 202
    advice_id = response.json()["id"]
    generated = client.get(f"/api/advice/{advice_id}").json()
    assert generated["status"] == "succeeded"
    assert generated["content"]["actions"][0]["evidence_refs"] == ["exercise-none-3d"]

    with SessionLocal() as db:
        set_tenant_context(db, alice.id)
        row = db.get(Advice, uuid.UUID(advice_id))
        context = json.loads(row.context_json)
        assert "username" not in row.context_json
        assert "photo" not in row.context_json
        assert context["notice"] == "健康习惯参考，不是医疗建议"

    feedback = client.post(
        f"/api/advice/{advice_id}/feedback",
        json={"feedback": "not_applicable", "reason": "晚上要照顾家人", "remember": True},
    )
    assert feedback.status_code == 200
    assert feedback.json()["feedback"] == "not_applicable"
    assert client.get("/api/notes").json()[0]["content"] == "晚上要照顾家人"

    repeated = client.post(
        f"/api/advice/{advice_id}/feedback",
        json={"feedback": "not_applicable", "reason": "晚上需要照顾孩子", "remember": True},
    )
    assert repeated.status_code == 200
    notes = client.get("/api/notes").json()
    assert len(notes) == 1
    assert notes[0]["content"] == "晚上需要照顾孩子"

    too_long = client.post(
        f"/api/advice/{advice_id}/feedback",
        json={"feedback": "not_applicable", "reason": "太" * 101, "remember": True},
    )
    assert too_long.status_code == 422
    assert client.get("/api/notes").json()[0]["content"] == "晚上需要照顾孩子"

    forgotten = client.post(
        f"/api/advice/{advice_id}/feedback",
        json={"feedback": "not_applicable", "reason": "临时情况", "remember": False},
    )
    assert forgotten.status_code == 200
    assert client.get("/api/notes").json() == []

    assert client.delete("/api/planning-consent").json()["granted"] is False


def test_safety_and_evidence_validation() -> None:
    unsafe = AdviceContent(
        summary="建议停药后观察。",
        actions=[
            AdviceAction(
                category="general",
                action="先记录感受。",
                rationale="资料有限。",
                evidence_refs=[],
                confidence="low",
            )
        ],
    )
    try:
        _validate_safety(unsafe, set())
        raise AssertionError("unsafe content should be rejected")
    except AdviceProviderError as exc:
        assert exc.code == "AI_UNSAFE_RESPONSE"

    invalid_ref = AdviceContent(
        summary="先从一个小行动开始。",
        actions=[
            AdviceAction(
                category="sleep",
                action="早点休息。",
                rationale="近期睡眠偏少。",
                evidence_refs=["invented"],
                confidence="medium",
            )
        ],
    )
    try:
        _validate_safety(invalid_ref, {"sleep-under-6h-3d"})
        raise AssertionError("invented evidence should be rejected")
    except AdviceProviderError as exc:
        assert exc.code == "AI_INVALID_EVIDENCE"

    medicine = AdviceContent(
        summary="先从一个小行动开始。",
        actions=[
            AdviceAction(
                category="diet",
                action="考虑使用减肥药物。",
                rationale="控制体重。",
                evidence_refs=[],
                confidence="low",
            )
        ],
    )
    with pytest.raises(AdviceProviderError, match="AI_UNSAFE_RESPONSE"):
        _validate_safety(medicine, set())

    unsupported = AdviceContent(
        summary="先从一个小行动开始。",
        actions=[
            AdviceAction(
                category="general",
                action="每天做一件小事。",
                rationale="建立习惯。",
                evidence_refs=[],
                confidence="high",
            )
        ],
    )
    with pytest.raises(AdviceProviderError, match="AI_INVALID_CONFIDENCE"):
        _validate_safety(unsupported, set())


def test_future_plan_rejects_actions_written_for_today() -> None:
    content = AdviceContent(
        summary="从一个小行动开始。",
        actions=[
            AdviceAction(
                category="exercise",
                action="今天晚饭后散步 15 分钟。",
                rationale="近期运动记录较少。",
                evidence_refs=["exercise-none-3d"],
                confidence="medium",
            )
        ],
    )
    context = {
        "plan": {"kind": "daily", "for_date": "2026-11-02"},
        "today": {"date": "2026-11-01"},
    }

    with pytest.raises(AdviceProviderError, match="AI_INVALID_PLAN_DATE"):
        _validate_plan_timing(content, context)

    content.actions[0].action = "明天晚饭后散步 15 分钟。"
    _validate_plan_timing(content, context)


def test_connection_error_becomes_provider_error(monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise httpx.ConnectError("dns failed")

    monkeypatch.setattr(httpx.Client, "post", fail)
    with pytest.raises(AdviceProviderError, match="AI_CONNECTION_ERROR"):
        generate_advice(
            {"observations": []},
            Settings(deepseek_api_key="test", deepseek_timeout_seconds=0.1),
        )


def _safe_check(summary: str, action: str = "先记录感受。") -> None:
    _validate_safety(
        AdviceContent(
            summary=summary,
            actions=[
                AdviceAction(
                    category="general",
                    action=action,
                    rationale="资料有限。",
                    evidence_refs=[],
                    confidence="low",
                )
            ],
        ),
        set(),
    )


@pytest.mark.parametrize(
    "summary",
    [
        "不建议断食，保持规律三餐。",
        "如有不适请咨询医生诊断。",
        "这不是医疗诊断，只是习惯参考。",
        "请勿擅自停药。",
        "This is not a diagnosis; avoid fasting.",
    ],
)
def test_safety_allows_negated_or_referral_phrases(summary: str) -> None:
    _safe_check(summary)


@pytest.mark.parametrize(
    "summary",
    [
        "不舒服时可以服用药物。",
        "不要错过服用保健品。",
        "建议尝试间歇断食。",
        "痛经时可以吃点止痛药。",
    ],
)
def test_safety_still_blocks_unsafe_phrases(summary: str) -> None:
    with pytest.raises(AdviceProviderError, match="AI_UNSAFE_RESPONSE"):
        _safe_check(summary)


def test_invalid_output_is_retried_once(monkeypatch) -> None:
    unsafe = {
        "summary": "建议服用保健品。",
        "actions": [
            {
                "category": "general",
                "action": "先记录感受。",
                "rationale": "资料有限。",
                "evidence_refs": [],
                "confidence": "low",
            }
        ],
        "limitations": [],
    }
    safe = {**unsafe, "summary": "先从一个小行动开始。"}
    replies = [unsafe, safe]
    calls = []

    def fake_post(_self, url, **_kwargs):
        calls.append(url)
        body = {"choices": [{"message": {"content": json.dumps(replies[len(calls) - 1], ensure_ascii=False)}}]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = generate_advice(
        {"observations": []},
        Settings(deepseek_api_key="test", deepseek_timeout_seconds=0.1),
    )
    assert len(calls) == 2
    assert result.content.summary == "先从一个小行动开始。"

    replies[1] = unsafe
    calls.clear()
    with pytest.raises(AdviceProviderError, match="AI_UNSAFE_RESPONSE"):
        generate_advice(
            {"observations": []},
            Settings(deepseek_api_key="test", deepseek_timeout_seconds=0.1),
        )
    assert len(calls) == 2


def test_unexpected_background_error_is_persisted(monkeypatch) -> None:
    create_user("alice")
    client = new_client()
    login(client, "alice")
    client.put("/api/planning-consent")
    monkeypatch.setattr(get_settings(), "deepseek_api_key", "test")

    def fail(_context, _settings):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(advice_service, "generate_advice", fail)
    created = client.post("/api/advice/daily", json={})
    assert created.status_code == 202
    result = client.get(f"/api/advice/{created.json()['id']}").json()
    assert result["status"] == "failed"
    assert result["error_code"] == "AI_INTERNAL_ERROR"


def test_context_contains_recent_feedback_and_matching_weekly_plan() -> None:
    user = create_user("alice")
    target = date.today() + timedelta(days=1)
    week_start = target - timedelta(days=target.weekday())
    content = AdviceContent(
        summary="本周保持轻量活动。",
        actions=[
            AdviceAction(
                category="exercise",
                action="晚饭后散步 15 分钟。",
                rationale="最近运动记录较少。",
                evidence_refs=["exercise-none-3d"],
                confidence="medium",
            )
        ],
        limitations=["这是健康习惯参考，不是医疗建议。"],
    )
    with SessionLocal() as db:
        attached_user = db.scalar(select(User).where(User.id == user.id))
        set_tenant_context(db, user.id)
        db.add_all(
            [
                Advice(
                    user_id=user.id,
                    kind="weekly",
                    for_date=datetime.combine(week_start, time.min, tzinfo=timezone.utc),
                    status="succeeded",
                    context_json="{}",
                    content_json=content.model_dump_json(),
                    observation_ids_json='["exercise-none-3d"]',
                    provider="deepseek",
                    model="test",
                    prompt_version="test",
                ),
                Advice(
                    user_id=user.id,
                    kind="daily",
                    for_date=datetime.now(timezone.utc),
                    status="succeeded",
                    context_json="{}",
                    content_json=content.model_dump_json(),
                    observation_ids_json='["exercise-none-3d"]',
                    feedback="not_applicable",
                    feedback_reason="晚上要照顾家人",
                    provider="deepseek",
                    model="test",
                    prompt_version="test",
                ),
            ]
        )
        commit_with_tenant_context(db, user.id)
        context, _observations = build_advice_context(
            db, attached_user, kind="daily", for_date=target
        )

    assert context["recent_feedback"][0]["actions"] == ["晚饭后散步 15 分钟。"]
    assert context["weekly_plan"]["actions"][0]["action"] == "晚饭后散步 15 分钟。"


def test_rejected_weekly_plan_is_not_used_for_daily_advice() -> None:
    user = create_user("alice")
    target = date.today() + timedelta(days=1)
    week_start = target - timedelta(days=target.weekday())
    content = AdviceContent(
        summary="本周保持轻量活动。",
        actions=[
            AdviceAction(
                category="exercise",
                action="晚饭后散步 15 分钟。",
                rationale="最近运动记录较少。",
                evidence_refs=["exercise-none-3d"],
                confidence="medium",
            )
        ],
    )
    with SessionLocal() as db:
        attached_user = db.scalar(select(User).where(User.id == user.id))
        set_tenant_context(db, user.id)
        db.add(
            Advice(
                user_id=user.id,
                kind="weekly",
                for_date=datetime.combine(week_start, time.min, tzinfo=timezone.utc),
                status="succeeded",
                context_json="{}",
                content_json=content.model_dump_json(),
                observation_ids_json='["exercise-none-3d"]',
                feedback="unsafe",
                feedback_reason="不适合当前身体状况",
                provider="deepseek",
                model="test",
                prompt_version="test",
            )
        )
        commit_with_tenant_context(db, user.id)
        context, _observations = build_advice_context(
            db, attached_user, kind="daily", for_date=target
        )

    assert context["weekly_plan"] is None


def test_old_pending_advice_is_marked_interrupted() -> None:
    user = create_user("alice")
    with SessionLocal() as db:
        set_tenant_context(db, user.id)
        stale = Advice(
            user_id=user.id,
            kind="daily",
            for_date=datetime.now(timezone.utc),
            status="pending",
            context_json="{}",
            observation_ids_json="[]",
            provider="deepseek",
            model="test",
            prompt_version="test",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.add(stale)
        commit_with_tenant_context(db, user.id)
        stale_id = stale.id

    client = new_client()
    login(client, "alice")
    result = client.get(f"/api/advice/{stale_id}").json()
    assert result["status"] == "failed"
    assert result["error_code"] == "AI_JOB_INTERRUPTED"


@pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL RLS integration test")
def test_postgres_rls_hides_notes_and_advice_from_other_users() -> None:
    alice = create_user("alice")
    bob = create_user("bob")
    with SessionLocal() as db:
        set_tenant_context(db, bob.id)
        note = UserNote(user_id=bob.id, content="Bob 的偏好", category="preference")
        advice = Advice(
            user_id=bob.id,
            kind="daily",
            for_date=datetime.now(timezone.utc),
            status="pending",
            context_json="{}",
            observation_ids_json="[]",
            provider="deepseek",
            model="test",
            prompt_version="test",
        )
        db.add_all([note, advice])
        db.commit()
        note_id, advice_id = note.id, advice.id

    with SessionLocal() as db:
        set_tenant_context(db, alice.id)
        assert db.scalar(select(UserNote).where(UserNote.id == note_id)) is None
        assert db.scalar(select(Advice).where(Advice.id == advice_id)) is None
