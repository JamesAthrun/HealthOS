"use client";

import { type FormEvent, useState } from "react";

import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import { localInputToIso, type Sleep, toDateTimeLocal } from "@/lib/health";
import { dayKey, formatMinutes, QUALITY_LABELS, shiftDay } from "@/lib/records";
import { useAction } from "@/lib/useAction";

import type { FormProps } from "./types";

function defaults(day: string | undefined) {
  const today = dayKey(new Date());
  if (!day || day === today) {
    const ended = new Date();
    return { started: toDateTimeLocal(new Date(ended.getTime() - 8 * 3_600_000)), ended: toDateTimeLocal(ended) };
  }
  return { started: `${shiftDay(day, -1)}T23:00`, ended: `${day}T07:00` };
}

export function SleepForm({ initial, day, onDone }: FormProps<Sleep>) {
  const confirm = useConfirm();
  const { busy, error, run } = useAction();
  const [startedAt, setStartedAt] = useState(() => initial ? toDateTimeLocal(initial.started_at) : defaults(day).started);
  const [endedAt, setEndedAt] = useState(() => initial ? toDateTimeLocal(initial.ended_at) : defaults(day).ended);
  const [quality, setQuality] = useState(initial?.quality ?? 3);
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const minutes = Math.round((new Date(endedAt).getTime() - new Date(startedAt).getTime()) / 60_000);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const body = {
      started_at: localInputToIso(startedAt),
      ended_at: localInputToIso(endedAt),
      quality,
      notes: notes || null,
    };
    const ok = await run(() => initial
      ? api(`/sleeps/${initial.id}`, { method: "PATCH", body })
      : api("/sleeps", { method: "POST", body }), "保存失败，请检查时间范围");
    if (ok) onDone(initial ? "已保存修改" : "睡眠已记录");
  }

  async function remove() {
    if (!initial || !(await confirm({ title: "删除这条睡眠记录？", message: "删除后无法恢复。", confirmText: "删除", danger: true }))) return;
    if (await run(() => api(`/sleeps/${initial.id}`, { method: "DELETE" }), "删除失败")) onDone("已删除");
  }

  return (
    <form className="stack" onSubmit={onSubmit}>
      {error && <p className="error" role="alert">{error}</p>}
      <label>入睡<input type="datetime-local" value={startedAt} onChange={(e) => setStartedAt(e.target.value)} required /></label>
      <label>醒来<input type="datetime-local" value={endedAt} onChange={(e) => setEndedAt(e.target.value)} required /></label>
      {minutes > 0 && <p className="muted">共 {formatMinutes(minutes)}</p>}
      <div>
        <span className="field-label">睡得怎么样</span>
        <div className="chips" role="group" aria-label="睡眠质量">
          {[1, 2, 3, 4, 5].map((value) => (
            <button key={value} type="button" aria-pressed={quality === value} onClick={() => setQuality(value)}>
              {QUALITY_LABELS[value]}
            </button>
          ))}
        </div>
      </div>
      <details className="more" open={Boolean(notes)}>
        <summary>备注（可选）</summary>
        <label>备注<textarea value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} /></label>
      </details>
      <button type="submit" disabled={busy}>{busy ? "保存中…" : "保存"}</button>
      {initial && <button type="button" className="ghost-danger" disabled={busy} onClick={() => void remove()}>删除这条记录</button>}
    </form>
  );
}
