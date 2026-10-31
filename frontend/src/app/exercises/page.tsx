"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import {
  type Exercise,
  formatLocalDateTime,
  localInputToIso,
  toDateTimeLocal,
} from "@/lib/health";
import { useMe } from "@/lib/useMe";

const INTENSITY_LABELS: Record<Exercise["intensity"], string> = {
  low: "低",
  moderate: "中",
  high: "高",
};

export default function ExercisesPage() {
  const me = useMe();
  const [rows, setRows] = useState<Exercise[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [type, setType] = useState("");
  const [startedAt, setStartedAt] = useState(toDateTimeLocal(new Date()));
  const [minutes, setMinutes] = useState("30");
  const [intensity, setIntensity] = useState<Exercise["intensity"]>("moderate");
  const [steps, setSteps] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    try {
      setRows(await api<Exercise[]>("/exercises"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "运动记录加载失败");
    }
  }

  useEffect(() => {
    let active = true;
    api<Exercise[]>("/exercises")
      .then((data) => { if (active) setRows(data); })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "运动记录加载失败"); });
    return () => { active = false; };
  }, []);

  function resetForm() {
    setEditingId(null);
    setType("");
    setStartedAt(toDateTimeLocal(new Date()));
    setMinutes("30");
    setIntensity("moderate");
    setSteps("");
    setNotes("");
  }

  function edit(row: Exercise) {
    setEditingId(row.id);
    setType(row.type);
    setStartedAt(toDateTimeLocal(row.started_at));
    setMinutes(String(row.minutes));
    setIntensity(row.intensity);
    setSteps(row.steps === null ? "" : String(row.steps));
    setNotes(row.notes ?? "");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    const body = {
      type,
      started_at: localInputToIso(startedAt),
      minutes: Number(minutes),
      intensity,
      steps: steps ? Number(steps) : null,
      notes: notes || null,
    };
    try {
      if (editingId) await api<Exercise>(`/exercises/${editingId}`, { method: "PATCH", body });
      else await api<Exercise>("/exercises", { method: "POST", body });
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("确认删除这条运动记录？")) return;
    try {
      await api(`/exercises/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    }
  }

  if (!me) return <p>加载中…</p>;

  return (
    <div className="stack">
      <form className="card stack" onSubmit={onSubmit}>
        <h1>{editingId ? "编辑运动" : "记录运动"}</h1>
        {error && <p className="error" role="alert">{error}</p>}
        <label>运动类型<input value={type} maxLength={50} onChange={(e) => setType(e.target.value)} placeholder="例如：快走、游泳" required /></label>
        <label>开始时间<input type="datetime-local" value={startedAt} onChange={(e) => setStartedAt(e.target.value)} required /></label>
        <label>时长（分钟）<input type="number" min="1" max="1440" value={minutes} onChange={(e) => setMinutes(e.target.value)} required /></label>
        <label>
          强度
          <select value={intensity} onChange={(e) => setIntensity(e.target.value as Exercise["intensity"])}>
            {Object.entries(INTENSITY_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>步数（可选）<input type="number" min="0" max="200000" value={steps} onChange={(e) => setSteps(e.target.value)} /></label>
        <label>备注<textarea value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} /></label>
        <button type="submit" disabled={submitting}>{submitting ? "保存中…" : editingId ? "保存修改" : "保存运动"}</button>
        {editingId && <button type="button" className="secondary" onClick={resetForm}>取消编辑</button>}
      </form>

      <section className="card">
        <h1>最近运动</h1>
        {rows.length === 0 ? <p className="muted">还没有运动记录</p> : rows.map((row) => (
          <article className="record-card" key={row.id}>
            <strong>{row.type} · {row.minutes} 分钟</strong>
            <p>{formatLocalDateTime(row.started_at)} · {INTENSITY_LABELS[row.intensity]}强度</p>
            {row.steps !== null && <p>{row.steps} 步</p>}
            {row.notes && <p className="muted">{row.notes}</p>}
            <div className="actions">
              <button type="button" className="secondary" onClick={() => edit(row)}>编辑</button>
              <button type="button" className="danger" onClick={() => void remove(row.id)}>删除</button>
            </div>
          </article>
        ))}
      </section>
      <Link href="/records/">返回记录</Link>
    </div>
  );
}
