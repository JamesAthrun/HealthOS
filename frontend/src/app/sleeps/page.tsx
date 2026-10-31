"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import {
  formatLocalDateTime,
  localInputToIso,
  type Sleep,
  toDateTimeLocal,
} from "@/lib/health";
import { useMe } from "@/lib/useMe";

function defaultSleepTimes() {
  const ended = new Date();
  const started = new Date(ended.getTime() - 8 * 60 * 60 * 1000);
  return { started: toDateTimeLocal(started), ended: toDateTimeLocal(ended) };
}

function duration(startedAt: string, endedAt: string): string {
  const minutes = Math.round((new Date(endedAt).getTime() - new Date(startedAt).getTime()) / 60_000);
  return `${Math.floor(minutes / 60)} 小时 ${minutes % 60} 分钟`;
}

export default function SleepsPage() {
  const me = useMe();
  const initial = defaultSleepTimes();
  const [rows, setRows] = useState<Sleep[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState(initial.started);
  const [endedAt, setEndedAt] = useState(initial.ended);
  const [quality, setQuality] = useState("3");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function load() {
    try {
      setRows(await api<Sleep[]>("/sleeps"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "睡眠记录加载失败");
    }
  }

  useEffect(() => {
    let active = true;
    api<Sleep[]>("/sleeps")
      .then((data) => { if (active) setRows(data); })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "睡眠记录加载失败"); });
    return () => { active = false; };
  }, []);

  function resetForm() {
    const next = defaultSleepTimes();
    setEditingId(null);
    setStartedAt(next.started);
    setEndedAt(next.ended);
    setQuality("3");
    setNotes("");
  }

  function edit(row: Sleep) {
    setEditingId(row.id);
    setStartedAt(toDateTimeLocal(row.started_at));
    setEndedAt(toDateTimeLocal(row.ended_at));
    setQuality(String(row.quality));
    setNotes(row.notes ?? "");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    const body = {
      started_at: localInputToIso(startedAt),
      ended_at: localInputToIso(endedAt),
      quality: Number(quality),
      notes: notes || null,
    };
    try {
      if (editingId) await api<Sleep>(`/sleeps/${editingId}`, { method: "PATCH", body });
      else await api<Sleep>("/sleeps", { method: "POST", body });
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存失败，请检查时间范围");
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm("确认删除这条睡眠记录？")) return;
    try {
      await api(`/sleeps/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    }
  }

  if (!me) return <p>加载中…</p>;

  return (
    <div className="stack">
      <form className="card stack" onSubmit={onSubmit}>
        <h1>{editingId ? "编辑睡眠" : "记录睡眠"}</h1>
        {error && <p className="error" role="alert">{error}</p>}
        <label>入睡时间<input type="datetime-local" value={startedAt} onChange={(e) => setStartedAt(e.target.value)} required /></label>
        <label>醒来时间<input type="datetime-local" value={endedAt} onChange={(e) => setEndedAt(e.target.value)} required /></label>
        <label>
          主观质量
          <select value={quality} onChange={(e) => setQuality(e.target.value)}>
            <option value="1">1 — 很差</option>
            <option value="2">2 — 较差</option>
            <option value="3">3 — 一般</option>
            <option value="4">4 — 较好</option>
            <option value="5">5 — 很好</option>
          </select>
        </label>
        <label>备注<textarea value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} /></label>
        <button type="submit" disabled={submitting}>{submitting ? "保存中…" : editingId ? "保存修改" : "保存睡眠"}</button>
        {editingId && <button type="button" className="secondary" onClick={resetForm}>取消编辑</button>}
      </form>

      <section className="card">
        <h1>最近睡眠</h1>
        {rows.length === 0 ? <p className="muted">还没有睡眠记录</p> : rows.map((row) => (
          <article className="record-card" key={row.id}>
            <strong>{duration(row.started_at, row.ended_at)} · 质量 {row.quality}/5</strong>
            <p>{formatLocalDateTime(row.started_at)} 至 {formatLocalDateTime(row.ended_at)}</p>
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
