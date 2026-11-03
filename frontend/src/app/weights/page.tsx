"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { signedKg, todayLocalDate, type WeightLog, type WeightSummary } from "@/lib/health";
import { useMe } from "@/lib/useMe";

const EMPTY_FORM = { measured_on: "", weight_kg: "", waist_cm: "", body_fat_pct: "", notes: "" };

export default function WeightsPage() {
  const me = useMe();
  const [rows, setRows] = useState<WeightLog[]>([]);
  const [summary, setSummary] = useState<WeightSummary | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState({ ...EMPTY_FORM, measured_on: todayLocalDate() });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    const [logs, stats] = await Promise.all([
      api<WeightLog[]>("/weights"),
      api<WeightSummary>("/weights/summary"),
    ]);
    setRows(logs);
    setSummary(stats);
  }

  useEffect(() => {
    if (!me) return;
    let active = true;
    Promise.all([api<WeightLog[]>("/weights"), api<WeightSummary>("/weights/summary")])
      .then(([logs, stats]) => {
        if (!active) return;
        setRows(logs);
        setSummary(stats);
      })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "体重记录加载失败"); });
    return () => { active = false; };
  }, [me]);

  function set(field: keyof typeof EMPTY_FORM, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function resetForm() {
    setEditingId(null);
    setForm({ ...EMPTY_FORM, measured_on: todayLocalDate() });
  }

  function edit(row: WeightLog) {
    setEditingId(row.id);
    setNotice("");
    setForm({
      measured_on: row.measured_on,
      weight_kg: String(row.weight_kg),
      waist_cm: row.waist_cm === null ? "" : String(row.waist_cm),
      body_fat_pct: row.body_fat_pct === null ? "" : String(row.body_fat_pct),
      notes: row.notes ?? "",
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setNotice("");
    setSubmitting(true);
    const numberOrNull = (value: string) => (value ? Number(value) : null);
    const body = {
      measured_on: form.measured_on,
      weight_kg: Number(form.weight_kg),
      waist_cm: numberOrNull(form.waist_cm),
      body_fat_pct: numberOrNull(form.body_fat_pct),
      notes: form.notes || null,
    };
    try {
      const saved = editingId
        ? await api<WeightLog>(`/weights/${editingId}`, { method: "PATCH", body })
        : await api<WeightLog>("/weights", { method: "POST", body });
      setNotice(saved.warning ? `已保存。${saved.warning}` : "已保存");
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存失败，请检查输入");
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("确认删除这条体重记录？")) return;
    try {
      await api(`/weights/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    }
  }

  if (!me) return <p>加载中…</p>;

  return (
    <div className="stack">
      {summary?.current && <SummaryCard summary={summary} />}

      <form className="card stack" onSubmit={onSubmit}>
        <h1>{editingId ? "编辑体重" : "记录体重"}</h1>
        <p className="muted">同一天只保留一条，重复保存会覆盖当天的记录。建议每天固定时间称重（如早起后）。</p>
        {error && <p className="error" role="alert">{error}</p>}
        {notice && <p className={notice === "已保存" ? "success" : "error"} role="status">{notice}</p>}
        <label>日期<input type="date" required max={todayLocalDate()} value={form.measured_on} onChange={(e) => set("measured_on", e.target.value)} /></label>
        <label>体重（公斤）<input type="number" required min="20" max="500" step="0.1" inputMode="decimal" value={form.weight_kg} onChange={(e) => set("weight_kg", e.target.value)} /></label>
        <label>腰围（厘米，可选）<input type="number" min="30" max="250" step="0.1" inputMode="decimal" value={form.waist_cm} onChange={(e) => set("waist_cm", e.target.value)} /></label>
        <label>体脂率（%，可选）<input type="number" min="2" max="75" step="0.1" inputMode="decimal" value={form.body_fat_pct} onChange={(e) => set("body_fat_pct", e.target.value)} /></label>
        <label>备注<textarea maxLength={500} value={form.notes} onChange={(e) => set("notes", e.target.value)} /></label>
        <button type="submit" disabled={submitting}>{submitting ? "保存中…" : editingId ? "保存修改" : "保存体重"}</button>
        {editingId && <button type="button" className="secondary" onClick={resetForm}>取消编辑</button>}
      </form>

      <section className="card">
        <h1>历史记录</h1>
        {rows.length === 0 ? <p className="muted">还没有体重记录</p> : rows.map((row) => (
          <article className="record-card" key={row.id}>
            <strong>{row.measured_on} · {row.weight_kg} kg</strong>
            {(row.waist_cm !== null || row.body_fat_pct !== null) && (
              <p>
                {row.waist_cm !== null && `腰围 ${row.waist_cm} cm`}
                {row.waist_cm !== null && row.body_fat_pct !== null && " · "}
                {row.body_fat_pct !== null && `体脂 ${row.body_fat_pct}%`}
              </p>
            )}
            {row.notes && <p className="muted">{row.notes}</p>}
            <div className="actions">
              <button type="button" className="secondary" onClick={() => edit(row)}>编辑</button>
              <button type="button" className="danger" onClick={() => void remove(row.id)}>删除</button>
            </div>
          </article>
        ))}
      </section>
      <Link href="/profile/">在健康档案中设置目标体重</Link>
      <Link href="/">返回首页</Link>
    </div>
  );
}

function SummaryCard({ summary }: { summary: WeightSummary }) {
  const current = summary.current!;
  return (
    <section className="card stack">
      <div>
        <p className="eyebrow">体重</p>
        <h1>{current.weight_kg} <small>kg</small></h1>
        <p className="muted">最近一次：{current.date}</p>
      </div>
      <div className="metric-grid">
        <article className="metric">
          <span>比初始</span>
          <strong>{summary.change_kg === null ? "—" : signedKg(summary.change_kg)} <small>kg</small></strong>
          <small>初始 {summary.initial?.weight_kg} kg · {summary.initial?.date}</small>
        </article>
        <article className="metric">
          <span>距目标</span>
          <strong>{summary.to_target_kg === null ? "—" : signedKg(summary.to_target_kg)} <small>kg</small></strong>
          <small>{summary.target_weight_kg ? `目标 ${summary.target_weight_kg} kg` : "尚未设置目标体重"}</small>
        </article>
        <article className="metric">
          <span>近 7 天</span>
          <strong>{summary.change_7d_kg === null ? "—" : signedKg(summary.change_7d_kg)} <small>kg</small></strong>
          <small>近 30 天 {summary.change_30d_kg === null ? "—" : `${signedKg(summary.change_30d_kg)} kg`}</small>
        </article>
        <article className="metric">
          <span>BMI</span>
          <strong>{summary.bmi ?? "—"}</strong>
          <small>{summary.bmi ? "18.5–23.9 为常用参考区间" : "填写身高后计算"}</small>
        </article>
      </div>
      {summary.trend.length >= 2 && <WeightChart points={summary.trend} target={summary.target_weight_kg} />}
      <small className="muted">{summary.notice}</small>
    </section>
  );
}

/** 最近 30 天：圆点是每次记录，线是 7 天平均；虚线是目标体重（在范围内时）。 */
function WeightChart({ points, target }: { points: WeightSummary["trend"]; target: number | null }) {
  const width = 320;
  const height = 140;
  const pad = 12;
  const days = (iso: string) => new Date(`${iso}T12:00:00`).getTime() / 86_400_000;
  const x0 = days(points[0].date);
  const span = Math.max(days(points[points.length - 1].date) - x0, 1);
  const values = points.flatMap((p) => [p.weight_kg, p.avg_7d_kg]);
  const min = Math.min(...values) - 0.5;
  const max = Math.max(...values) + 0.5;
  const x = (iso: string) => pad + ((days(iso) - x0) / span) * (width - pad * 2);
  const y = (kg: number) => pad + ((max - kg) / (max - min)) * (height - pad * 2);
  const avgPath = points.map((p, i) => `${i ? "L" : "M"}${x(p.date).toFixed(1)},${y(p.avg_7d_kg).toFixed(1)}`).join(" ");

  return (
    <figure className="stack">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="最近 30 天体重趋势" style={{ width: "100%", height: "auto" }}>
        {target !== null && target >= min && target <= max && (
          <line x1={pad} x2={width - pad} y1={y(target)} y2={y(target)} stroke="var(--muted)" strokeDasharray="4 4" />
        )}
        <path d={avgPath} fill="none" stroke="var(--primary)" strokeWidth="2" />
        {points.map((p) => (
          <circle key={p.date} cx={x(p.date)} cy={y(p.weight_kg)} r="3" fill="var(--primary)" opacity="0.5" />
        ))}
      </svg>
      <figcaption className="muted">
        最近 30 天 · 圆点为每次记录，曲线为 7 天平均{target !== null && "，虚线为目标"}（{min.toFixed(1)}–{max.toFixed(1)} kg）
      </figcaption>
    </figure>
  );
}
