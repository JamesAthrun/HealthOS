"use client";

import { type FormEvent, useState } from "react";

import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import { type Exercise, localInputToIso, toDateTimeLocal } from "@/lib/health";
import { defaultDateTime, INTENSITY_LABELS } from "@/lib/records";
import { useAction } from "@/lib/useAction";

import type { FormProps } from "./types";

const COMMON_TYPES = ["走路", "跑步", "健身", "网球", "游泳", "骑行", "瑜伽", "羽毛球", "篮球"];

export function ExerciseForm({ initial, day, onDone }: FormProps<Exercise>) {
  const confirm = useConfirm();
  const { busy, error, run } = useAction();
  const [type, setType] = useState(initial?.type ?? "");
  const [startedAt, setStartedAt] = useState(initial ? toDateTimeLocal(initial.started_at) : defaultDateTime(day, "18:00"));
  const [minutes, setMinutes] = useState(initial ? String(initial.minutes) : "30");
  const [intensity, setIntensity] = useState<Exercise["intensity"]>(initial?.intensity ?? "moderate");
  const [steps, setSteps] = useState(initial?.steps == null ? "" : String(initial.steps));
  const [notes, setNotes] = useState(initial?.notes ?? "");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const body = {
      type,
      started_at: localInputToIso(startedAt),
      minutes: Number(minutes),
      intensity,
      steps: steps ? Number(steps) : null,
      notes: notes || null,
    };
    const ok = await run(() => initial
      ? api(`/exercises/${initial.id}`, { method: "PATCH", body })
      : api("/exercises", { method: "POST", body }), "保存失败，请稍后重试");
    if (ok) onDone(initial ? "已保存修改" : "运动已记录");
  }

  async function remove() {
    if (!initial || !(await confirm({ title: "删除这条运动记录？", message: "删除后无法恢复。", confirmText: "删除", danger: true }))) return;
    if (await run(() => api(`/exercises/${initial.id}`, { method: "DELETE" }), "删除失败")) onDone("已删除");
  }

  return (
    <form className="stack" onSubmit={onSubmit}>
      {error && <p className="error" role="alert">{error}</p>}
      <div>
        <span className="field-label">做了什么</span>
        <div className="chips" role="group" aria-label="常用运动">
          {COMMON_TYPES.map((name) => (
            <button key={name} type="button" aria-pressed={type === name} onClick={() => setType(name)}>{name}</button>
          ))}
        </div>
      </div>
      <label>其他运动<input value={type} maxLength={50} onChange={(e) => setType(e.target.value)} placeholder="或直接输入" required /></label>
      <div className="two-col">
        <label>时长（分钟）<input type="number" inputMode="numeric" min="1" max="1440" value={minutes} onChange={(e) => setMinutes(e.target.value)} required /></label>
        <label>开始时间<input type="datetime-local" value={startedAt} onChange={(e) => setStartedAt(e.target.value)} required /></label>
      </div>
      <div>
        <span className="field-label">强度</span>
        <div className="chips" role="group" aria-label="强度">
          {(Object.keys(INTENSITY_LABELS) as Exercise["intensity"][]).map((value) => (
            <button key={value} type="button" aria-pressed={intensity === value} onClick={() => setIntensity(value)}>
              {INTENSITY_LABELS[value]}
            </button>
          ))}
        </div>
      </div>
      <details className="more" open={Boolean(steps || notes)}>
        <summary>步数、备注（可选）</summary>
        <label>步数<input type="number" inputMode="numeric" min="0" max="200000" value={steps} onChange={(e) => setSteps(e.target.value)} /></label>
        <label>备注<textarea value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} /></label>
      </details>
      <button type="submit" disabled={busy}>{busy ? "保存中…" : "保存"}</button>
      {initial && <button type="button" className="ghost-danger" disabled={busy} onClick={() => void remove()}>删除这条记录</button>}
    </form>
  );
}
