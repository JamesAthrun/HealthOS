"use client";

import Link from "next/link";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import {
  type CycleFlow,
  cycleHeadline,
  type CyclePeriod,
  type CycleSettingsOut,
  type CycleSummary,
  type CycleSymptom,
  FLOW_LABELS,
  monthDay,
  PHASE_LABELS,
  SYMPTOM_LABELS,
} from "@/lib/cycle";
import { todayLocalDate } from "@/lib/health";
import { useMe } from "@/lib/useMe";

type FormState = {
  start_date: string;
  end_date: string;
  flow: CycleFlow | "";
  symptoms: CycleSymptom[];
  notes: string;
};

const emptyForm = (): FormState => ({ start_date: todayLocalDate(), end_date: "", flow: "", symptoms: [], notes: "" });

function fetchCycle() {
  return Promise.all([api<CycleSummary>("/cycles/summary"), api<CyclePeriod[]>("/cycles")]);
}

function periodDays(period: CyclePeriod): number | null {
  if (!period.end_date) return null;
  const ms = new Date(`${period.end_date}T12:00:00`).getTime() - new Date(`${period.start_date}T12:00:00`).getTime();
  return Math.round(ms / 86_400_000) + 1;
}

export default function CyclePage() {
  const me = useMe();
  const confirm = useConfirm();
  const [settings, setSettings] = useState<CycleSettingsOut | null>(null);
  const [summary, setSummary] = useState<CycleSummary | null>(null);
  const [periods, setPeriods] = useState<CyclePeriod[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const next = await api<CycleSettingsOut>("/cycle-settings");
      setSettings(next);
      if (next.available && next.tracking_enabled) {
        const [s, list] = await fetchCycle();
        setSummary(s);
        setPeriods(list);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败，请稍后重试");
    }
  }, []);

  useEffect(() => {
    if (!me) return;
    let active = true;
    (async () => {
      try {
        const next = await api<CycleSettingsOut>("/cycle-settings");
        const data = next.available && next.tracking_enabled ? await fetchCycle() : null;
        if (!active) return;
        setSettings(next);
        if (data) {
          setSummary(data[0]);
          setPeriods(data[1]);
        }
      } catch (err) {
        if (active) setError(err instanceof ApiError ? err.message : "加载失败，请稍后重试");
      }
    })();
    return () => { active = false; };
  }, [me]);

  if (!me || settings === null) return <p>{error || "加载中…"}</p>;

  async function saveSettings(patch: Partial<CycleSettingsOut>) {
    if (!settings) return;
    const { tracking_enabled, share_with_ai, adjust_targets } = { ...settings, ...patch };
    await run(() => api("/cycle-settings", { method: "PUT", body: { tracking_enabled, share_with_ai, adjust_targets } }));
  }

  if (!settings.available) {
    return (
      <section className="card stack">
        <h1>生理周期</h1>
        <p>健康档案里的性别选“女”后才能使用周期记录。</p>
        <Link href="/profile/">去健康档案</Link>
      </section>
    );
  }

  if (!settings.tracking_enabled) {
    return (
      <section className="card stack">
        <h1>生理周期</h1>
        <p>记录经期，估算下次时间；经前自动给热量参考加一点，经期提醒补铁。</p>
        <p className="muted">仅本人可见，默认不发送给 AI，随时可以关闭。</p>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="button" disabled={busy} onClick={() => void saveSettings({ tracking_enabled: true })}>开启周期记录</button>
      </section>
    );
  }

  const ongoing = periods.find((p) => p.end_date === null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作失败，请稍后重试");
    } finally {
      setBusy(false);
    }
  }

  function edit(period: CyclePeriod) {
    setEditingId(period.id);
    setForm({
      start_date: period.start_date,
      end_date: period.end_date ?? "",
      flow: period.flow ?? "",
      symptoms: period.symptoms,
      notes: period.notes ?? "",
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function resetForm() {
    setEditingId(null);
    setForm(emptyForm());
  }

  function toggleSymptom(symptom: CycleSymptom) {
    setForm((current) => ({
      ...current,
      symptoms: current.symptoms.includes(symptom)
        ? current.symptoms.filter((s) => s !== symptom)
        : [...current.symptoms, symptom],
    }));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const body = {
      start_date: form.start_date,
      end_date: form.end_date || null,
      flow: form.flow || null,
      symptoms: form.symptoms,
      notes: form.notes || null,
    };
    await run(async () => {
      if (editingId) await api(`/cycles/${editingId}`, { method: "PATCH", body });
      else await api("/cycles", { method: "POST", body });
      resetForm();
    });
  }

  async function remove(id: string) {
    if (!(await confirm({ title: "删除这条经期记录？", message: "删除后无法恢复。", confirmText: "删除", danger: true }))) return;
    await run(() => api(`/cycles/${id}`, { method: "DELETE" }));
  }

  async function removeAll() {
    if (!(await confirm({ title: "删除全部周期记录？", message: "所有经期记录都会被永久删除，无法恢复。", confirmText: "全部删除", danger: true }))) return;
    await run(() => api("/cycles", { method: "DELETE" }));
  }

  const headline = summary ? cycleHeadline(summary) : null;

  return (
    <div className="stack">
      <section className="card stack">
        <div>
          <p className="eyebrow">生理周期</p>
          <h1>{headline?.title === "—" ? "还没有记录" : headline?.title}</h1>
          {summary?.has_data && summary.phase && !summary.in_period && summary.phase !== "late" && (
            <p className="muted">当前阶段：{PHASE_LABELS[summary.phase]}</p>
          )}
          {headline && headline.title !== "—" && <p>{headline.detail}</p>}
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        {ongoing ? (
          <button type="button" disabled={busy} onClick={() => run(() => api("/cycles/end-today", { method: "POST" }))}>今天结束了</button>
        ) : (
          <button type="button" disabled={busy} onClick={() => run(() => api("/cycles/start-today", { method: "POST" }))}>今天来了</button>
        )}
        {summary?.has_data && (
          <div className="reference">
            <p>平均周期约 {summary.avg_cycle_days} 天，经期约 {summary.avg_period_days} 天。</p>
            {summary.next_start_earliest && summary.next_start_latest && summary.late_days === null && (
              <p>下次大约在 {monthDay(summary.next_start_earliest)} – {monthDay(summary.next_start_latest)} 之间。</p>
            )}
            {summary.insufficient_data && <p>数据不足（少于 2 个完整周期），按 28 天估算，预测仅供参考。</p>}
          </div>
        )}
        {summary && summary.alerts.length > 0 && (
          <ul className="warning-list">
            {summary.alerts.map((alert) => <li key={alert}>{alert}</li>)}
          </ul>
        )}
        {summary && summary.tips.length > 0 && (
          <ul className="tip-list">
            {summary.tips.map((tip) => <li key={tip}><span aria-hidden="true">🌸</span>{tip}</li>)}
          </ul>
        )}
        {summary && <p className="muted">{summary.notice}</p>}
      </section>

      <form className="card stack" onSubmit={onSubmit}>
        <h2>{editingId ? "修改记录" : "补录一次经期"}</h2>
        <label>
          开始日期
          <input type="date" required max={todayLocalDate()} value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
        </label>
        <label>
          结束日期（还没结束可留空）
          <input type="date" min={form.start_date} max={todayLocalDate()} value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
        </label>
        <label>
          经量
          <select value={form.flow} onChange={(e) => setForm({ ...form, flow: e.target.value as CycleFlow | "" })}>
            <option value="">不记录</option>
            {Object.entries(FLOW_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <div>
          <span className="muted">症状（可多选）</span>
          <div className="choice-grid">
            {(Object.keys(SYMPTOM_LABELS) as CycleSymptom[]).map((symptom) => (
              <button
                key={symptom}
                type="button"
                className="secondary"
                aria-pressed={form.symptoms.includes(symptom)}
                onClick={() => toggleSymptom(symptom)}
              >
                {SYMPTOM_LABELS[symptom]}
              </button>
            ))}
          </div>
        </div>
        <label>
          备注
          <textarea maxLength={500} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
        </label>
        <button type="submit" disabled={busy}>{busy ? "保存中…" : editingId ? "保存修改" : "保存记录"}</button>
        {editingId && <button type="button" className="secondary" onClick={resetForm}>取消编辑</button>}
      </form>

      <section className="card">
        <h2>历史记录</h2>
        {periods.length === 0 ? <p className="muted">还没有记录</p> : periods.map((period) => {
          const days = periodDays(period);
          return (
            <article className="record-card" key={period.id}>
              <strong>
                {monthDay(period.start_date)}
                {period.end_date ? ` – ${monthDay(period.end_date)}（${days} 天）` : " 起 · 进行中"}
              </strong>
              {(period.flow || period.symptoms.length > 0) && (
                <p className="muted">
                  {[period.flow && `经量${FLOW_LABELS[period.flow]}`, ...period.symptoms.map((s) => SYMPTOM_LABELS[s])].filter(Boolean).join(" · ")}
                </p>
              )}
              {period.notes && <p className="muted">{period.notes}</p>}
              <div className="actions">
                <button type="button" className="secondary" onClick={() => edit(period)}>编辑</button>
                <button type="button" className="danger" onClick={() => void remove(period.id)}>删除</button>
              </div>
            </article>
          );
        })}
      </section>

      {periods.length > 0 && (
        <section className="card stack">
          <p className="muted">关闭周期记录不会删除历史；如需彻底删除，请使用下面的按钮。</p>
          <button type="button" className="danger" disabled={busy} onClick={() => void removeAll()}>删除全部周期记录</button>
        </section>
      )}

      <section className="card stack">
        <h2>设置</h2>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={settings.adjust_targets}
            disabled={busy}
            onChange={(e) => void saveSettings({ adjust_targets: e.target.checked })}
          />
          按周期调整饮食参考
        </label>
        <p className="muted">经前每日热量参考 +150 kcal，经期显示补铁提示。</p>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={settings.share_with_ai}
            disabled={busy}
            onChange={(e) => void saveSettings({ share_with_ai: e.target.checked })}
          />
          生成建议时参考周期
        </label>
        <p className="muted">开启后，生成每日建议和周计划时会把当前阶段、周期第几天和最近一次记录的症状发给 AI（不发送具体日期和历史），建议会按经期、经前调整运动和饮食。默认关闭，随时可以关掉。</p>
        <button type="button" className="secondary" disabled={busy} onClick={() => void saveSettings({ tracking_enabled: false })}>
          关闭周期记录
        </button>
      </section>
    </div>
  );
}
