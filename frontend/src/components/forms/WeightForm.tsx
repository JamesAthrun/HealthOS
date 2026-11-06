"use client";

import { type FormEvent, useState } from "react";

import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import { todayLocalDate, type WeightLog } from "@/lib/health";
import { useAction } from "@/lib/useAction";

import type { FormProps } from "./types";

const optional = (value: number | null | undefined) => (value == null ? "" : String(value));
const numberOrNull = (value: string) => (value ? Number(value) : null);

export function WeightForm({ initial, day, onDone }: FormProps<WeightLog>) {
  const confirm = useConfirm();
  const { busy, error, run } = useAction();
  const [measuredOn, setMeasuredOn] = useState(initial?.measured_on ?? day ?? todayLocalDate());
  const [weight, setWeight] = useState(optional(initial?.weight_kg));
  const [waist, setWaist] = useState(optional(initial?.waist_cm));
  const [bodyFat, setBodyFat] = useState(optional(initial?.body_fat_pct));
  const [notes, setNotes] = useState(initial?.notes ?? "");

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const body = {
      measured_on: measuredOn,
      weight_kg: Number(weight),
      waist_cm: numberOrNull(waist),
      body_fat_pct: numberOrNull(bodyFat),
      notes: notes || null,
    };
    const result: { saved?: WeightLog } = {};
    const ok = await run(async () => {
      result.saved = initial
        ? await api<WeightLog>(`/weights/${initial.id}`, { method: "PATCH", body })
        : await api<WeightLog>("/weights", { method: "POST", body });
    }, "保存失败，请检查输入");
    if (!ok) return;
    const warning = result.saved?.warning;
    if (warning) onDone(`已保存。${warning}`, "warning");
    else onDone(initial ? "已保存修改" : "体重已记录");
  }

  async function remove() {
    if (!initial || !(await confirm({ title: "删除这条体重记录？", message: "删除后无法恢复。", confirmText: "删除", danger: true }))) return;
    if (await run(() => api(`/weights/${initial.id}`, { method: "DELETE" }), "删除失败")) onDone("已删除");
  }

  return (
    <form className="stack" onSubmit={onSubmit}>
      {error && <p className="error" role="alert">{error}</p>}
      <div className="two-col">
        <label>体重（kg）<input type="number" required min="20" max="500" step="0.1" inputMode="decimal" value={weight} onChange={(e) => setWeight(e.target.value)} autoFocus={!initial} /></label>
        <label>日期<input type="date" required max={todayLocalDate()} value={measuredOn} onChange={(e) => setMeasuredOn(e.target.value)} /></label>
      </div>
      <p className="muted">同一天只保留一条，重复保存会覆盖。建议每天固定时间称（如早起后）。</p>
      <details className="more" open={Boolean(waist || bodyFat || notes)}>
        <summary>腰围、体脂、备注（可选）</summary>
        <div className="two-col">
          <label>腰围（cm）<input type="number" min="30" max="250" step="0.1" inputMode="decimal" value={waist} onChange={(e) => setWaist(e.target.value)} /></label>
          <label>体脂率（%）<input type="number" min="2" max="75" step="0.1" inputMode="decimal" value={bodyFat} onChange={(e) => setBodyFat(e.target.value)} /></label>
        </div>
        <label>备注<textarea maxLength={500} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
      </details>
      <button type="submit" disabled={busy}>{busy ? "保存中…" : "保存"}</button>
      {initial && <button type="button" className="ghost-danger" disabled={busy} onClick={() => void remove()}>删除这条记录</button>}
    </form>
  );
}
