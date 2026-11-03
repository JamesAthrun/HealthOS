"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/useMe";
import { FoodPrefButtons, useFoodPreferences } from "@/lib/foodPrefs";

type Consent = { granted: boolean; granted_at: string | null };
type AdviceAction = {
  category: "diet" | "exercise" | "sleep" | "general";
  action: string;
  rationale: string;
  evidence_refs: string[];
  confidence: "low" | "medium" | "high";
};
type MealPlanGroup = {
  meal_type: "breakfast" | "lunch" | "dinner" | "snack";
  items: { name: string; portion: string; approx_kcal: number }[];
  reason: string;
};
type Advice = {
  id: string;
  kind: "daily" | "weekly";
  for_date: string;
  status: "pending" | "succeeded" | "failed";
  content: { summary: string; actions: AdviceAction[]; limitations: string[]; meal_plan: MealPlanGroup[] } | null;
  feedback: string | null;
  error_code: string | null;
  created_at: string;
};
type FeedbackValue = "useful" | "not_applicable" | "unsafe";
type FeedbackDraft = { feedback: FeedbackValue; reason: string; remember: boolean };

const CATEGORY_LABELS = { diet: "饮食", exercise: "运动", sleep: "睡眠", general: "日常" };
const MEAL_LABELS = { breakfast: "早餐", lunch: "午餐", dinner: "晚餐", snack: "加餐" };

export default function AdvicePage() {
  const me = useMe();
  const [consent, setConsent] = useState<Consent | null>(null);
  const [items, setItems] = useState<Advice[]>([]);
  const [busy, setBusy] = useState<"daily" | "weekly" | "">("");
  const [feedbackBusy, setFeedbackBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [feedbackDrafts, setFeedbackDrafts] = useState<Record<string, FeedbackDraft>>({});
  const foodPrefs = useFoodPreferences(Boolean(me));

  const load = useCallback(async () => {
    const [nextConsent, nextItems] = await Promise.all([
      api<Consent>("/planning-consent"),
      api<Advice[]>("/advice"),
    ]);
    setConsent(nextConsent);
    setItems(nextItems);
  }, []);

  useEffect(() => {
    if (!me) return;
    Promise.all([
      api<Consent>("/planning-consent"),
      api<Advice[]>("/advice"),
    ])
      .then(([nextConsent, nextItems]) => {
        setConsent(nextConsent);
        setItems(nextItems);
      })
      .catch(() => setError("规划加载失败，请稍后重试"));
  }, [me]);

  useEffect(() => {
    if (!items.some((item) => item.status === "pending")) return;
    const timer = window.setInterval(() => {
      api<Advice[]>("/advice").then(setItems).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(timer);
  }, [items]);

  if (!me) return <p>加载中…</p>;

  async function grantConsent() {
    setError("");
    try {
      setConsent(await api<Consent>("/planning-consent", { method: "PUT" }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作失败，请稍后重试");
    }
  }

  async function generate(kind: "daily" | "weekly") {
    setBusy(kind);
    setError("");
    try {
      await api<Advice>(`/advice/${kind}`, { method: "POST", body: {} });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "生成失败，请稍后重试");
    } finally {
      setBusy("");
    }
  }

  function updateFeedbackDraft(id: string, change: Partial<FeedbackDraft>) {
    setFeedbackDrafts((current) => ({
      ...current,
      [id]: {
        feedback: current[id]?.feedback ?? "useful",
        reason: current[id]?.reason ?? "",
        remember: current[id]?.remember ?? false,
        ...change,
      },
    }));
  }

  async function submitFeedback(item: Advice) {
    const draft = feedbackDrafts[item.id] ?? {
      feedback: "useful" as const,
      reason: "",
      remember: false,
    };
    setFeedbackBusy(item.id);
    setError("");
    try {
      const updated = await api<Advice>(`/advice/${item.id}/feedback`, {
        method: "POST",
        body: {
          feedback: draft.feedback,
          reason: draft.reason || null,
          remember: draft.feedback === "not_applicable" && draft.remember,
        },
      });
      setItems((current) => current.map((candidate) => candidate.id === updated.id ? updated : candidate));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "反馈保存失败");
    } finally {
      setFeedbackBusy(null);
    }
  }

  return (
    <div className="stack">
      <section className="card stack">
        <div>
          <p className="eyebrow">Sprint 4</p>
          <h1>健康规划</h1>
          <p>根据你的聚合记录生成小步、可执行的明日建议或周计划。</p>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {consent && !consent.granted && (
          <div className="consent-box">
            <p>生成时会把近 30 天的聚合健康摘要、体重变化、“关于我”、你标记的食物偏好和近 30 天常吃的食物名称、最近建议，以及你填写的评价和反馈原因发送给 DeepSeek。不会发送用户名、照片或饮食、运动、睡眠的原始备注。本同意与餐食照片处理相互独立，可随时撤回。</p>
            <button type="button" onClick={grantConsent}>同意使用健康摘要生成规划</button>
          </div>
        )}
        <div className="actions">
          <button type="button" disabled={!consent?.granted || busy !== ""} onClick={() => generate("daily")}>
            {busy === "daily" ? "生成中…" : "生成明日建议"}
          </button>
          <button type="button" disabled={!consent?.granted || busy !== ""} onClick={() => generate("weekly")}>
            {busy === "weekly" ? "生成中…" : "生成下周计划"}
          </button>
        </div>
        <Link href="/notes/">管理“关于我”</Link>
      </section>

      {items.length === 0 && <section className="card"><p className="muted">还没有规划。先完善健康记录和“关于我”，再生成第一份建议。</p></section>}
      {items.map((item) => {
        const draft = feedbackDrafts[item.id] ?? {
          feedback: "useful" as FeedbackValue,
          reason: "",
          remember: false,
        };
        return <article className="card stack" key={item.id}>
          <div>
            <p className="eyebrow">{item.kind === "daily" ? "明日建议" : "周计划"} · {item.for_date}</p>
            <h2>{item.status === "pending" ? "正在生成…" : item.content?.summary ?? "生成失败"}</h2>
          </div>
          {item.status === "failed" && <p className="error">本次未生成成功（{item.error_code}），可以稍后重试。</p>}
          {item.content?.actions.map((action, index) => (
            <section className="advice-action" key={`${action.category}-${index}`}>
              <strong>{CATEGORY_LABELS[action.category]} · {action.action}</strong>
              <p>{action.rationale}</p>
              <small>把握：{action.confidence === "high" ? "较高" : action.confidence === "medium" ? "中等" : "较低"}</small>
            </section>
          ))}
          {item.content && item.content.limitations.length > 0 && (
            <ul className="warning-list">{item.content.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
          )}
          {item.content && item.content.meal_plan?.length > 0 && (
            <section className="stack" aria-label="参考餐单">
              <h3>参考餐单</h3>
              {foodPrefs.error && <p className="error" role="alert">{foodPrefs.error}</p>}
              {item.content.meal_plan.map((group) => (
                <section className="advice-action" key={group.meal_type}>
                  <strong>
                    {MEAL_LABELS[group.meal_type]} · 约 {group.items.reduce((sum, food) => sum + food.approx_kcal, 0)} kcal
                  </strong>
                  {group.items.map((food) => (
                    <div className="pref-row" key={food.name}>
                      <span>{food.name}，{food.portion}，约 {food.approx_kcal} kcal</span>
                      <FoodPrefButtons name={food.name} current={foodPrefs.find(food.name)?.sentiment} onToggle={foodPrefs.toggle} />
                    </div>
                  ))}
                  <small>{group.reason}</small>
                </section>
              ))}
              <p className="muted">已按档案中的过敏信息和“不想再吃”过滤；如发现遗漏，请补充到档案的过敏信息中。</p>
            </section>
          )}
          {item.status === "succeeded" && (
            item.feedback ? <p className="muted">反馈已保存：{item.feedback === "useful" ? "有帮助" : item.feedback === "unsafe" ? "不安全" : "不适用"}</p> :
            <section className="feedback-box stack" aria-label="评价建议">
              <label>
                这份建议对你来说
                <select
                  value={draft.feedback}
                  onChange={(event) => updateFeedbackDraft(item.id, {
                    feedback: event.target.value as FeedbackValue,
                    remember: event.target.value === "not_applicable" ? draft.remember : false,
                  })}
                >
                  <option value="useful">有帮助</option>
                  <option value="not_applicable">不适用</option>
                  <option value="unsafe">不安全</option>
                </select>
              </label>
              <label>
                原因（可选）
                <textarea
                  maxLength={draft.remember ? 100 : 500}
                  value={draft.reason}
                  onChange={(event) => updateFeedbackDraft(item.id, { reason: event.target.value })}
                  placeholder="例如：晚上需要照顾家人，无法安排散步"
                />
                {draft.remember && <small className="muted">勾选记住时最多 100 字（当前 {draft.reason.length} 字）</small>}
              </label>
              {draft.feedback === "not_applicable" && (
                <label className="checkbox-label">
                  <input
                    type="checkbox"
                    checked={draft.remember}
                    onChange={(event) => updateFeedbackDraft(item.id, { remember: event.target.checked })}
                  />
                  记住这一点，用于之后的建议
                </label>
              )}
              <button
                type="button"
                className="secondary"
                disabled={
                  feedbackBusy === item.id
                  || (draft.remember && (!draft.reason.trim() || draft.reason.length > 100))
                }
                onClick={() => submitFeedback(item)}
              >
                {feedbackBusy === item.id ? "保存中…" : "保存反馈"}
              </button>
            </section>
          )}
        </article>;
      })}
      <p className="muted">HealthOS 规划仅供健康习惯参考，不是医疗建议。</p>
      <Link href="/">返回首页</Link>
    </div>
  );
}
