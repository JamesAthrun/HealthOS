"use client";

import { type FormEvent, useState } from "react";

import { FoodItemsEditor } from "@/components/FoodItemsEditor";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import { useFoodPreferences } from "@/lib/foodPrefs";
import { localInputToIso, type Meal, toDateTimeLocal } from "@/lib/health";
import { type DraftItem, emptyFoodItem, NutritionCard, toFoodItem } from "@/lib/nutrition";
import { defaultDateTime, MEAL_LABELS } from "@/lib/records";
import { useAction } from "@/lib/useAction";

import type { FormProps } from "./types";

export function guessMealType(date: Date = new Date()): Meal["meal_type"] {
  const hour = date.getHours();
  if (hour < 10) return "breakfast";
  if (hour < 15) return "lunch";
  if (hour < 17) return "snack";
  if (hour < 22) return "dinner";
  return "snack";
}

export function MealTypeChips({ value, onChange }: { value: Meal["meal_type"]; onChange: (value: Meal["meal_type"]) => void }) {
  return (
    <div>
      <span className="field-label">餐次</span>
      <div className="chips" role="group" aria-label="餐次">
        {(Object.keys(MEAL_LABELS) as Meal["meal_type"][]).map((type) => (
          <button key={type} type="button" aria-pressed={value === type} onClick={() => onChange(type)}>{MEAL_LABELS[type]}</button>
        ))}
      </div>
    </div>
  );
}

/** AI 识别出的草稿：拍照时带 photoId，确认时走照片确认接口 */
export type MealDraft = {
  items: DraftItem[];
  mealType: Meal["meal_type"];
  photoId?: string;
  confidence?: number;
  warnings?: string[];
};

export function MealForm({ initial, day, draft, onDone }: FormProps<Meal> & { draft?: MealDraft }) {
  const confirm = useConfirm();
  const prefs = useFoodPreferences(true);
  const { busy, error, run } = useAction();
  const [eatenAt, setEatenAt] = useState(() => initial ? toDateTimeLocal(initial.eaten_at) : defaultDateTime(day, "12:00"));
  const [mealType, setMealType] = useState<Meal["meal_type"]>(
    () => initial?.meal_type ?? draft?.mealType ?? guessMealType(new Date(eatenAt)),
  );
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [items, setItems] = useState<DraftItem[]>(() => {
    if (initial) {
      return initial.food_items.map((food) => {
        const copy: DraftItem & { id?: string } = { ...food };
        delete copy.id;
        return copy;
      });
    }
    return draft?.items.length ? draft.items : [emptyFoodItem()];
  });

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const body = {
      eaten_at: localInputToIso(eatenAt),
      meal_type: mealType,
      notes: notes || null,
      food_items: items.map(toFoodItem),
    };
    const ok = await run(() => {
      if (initial) return api(`/meals/${initial.id}`, { method: "PATCH", body });
      if (draft?.photoId) return api(`/meal-photos/${draft.photoId}/confirm`, { method: "POST", body });
      return api("/meals", { method: "POST", body });
    }, "保存失败，请稍后重试");
    if (ok) onDone(initial ? "已保存修改" : "饮食已记录");
  }

  async function remove() {
    if (!initial || !(await confirm({ title: "删除这条饮食记录？", message: "删除后无法恢复。", confirmText: "删除", danger: true }))) return;
    if (await run(() => api(`/meals/${initial.id}`, { method: "DELETE" }), "删除失败")) onDone("已删除");
  }

  return (
    <form className="stack" onSubmit={onSubmit}>
      {error && <p className="error" role="alert">{error}</p>}
      {prefs.error && <p className="error" role="alert">{prefs.error}</p>}
      {draft && <NutritionCard items={items} note="AI 粗略估算，仅供参考，可以直接修改下面的内容；改份量会按比例换算。" />}
      {draft?.confidence !== undefined && <p className="muted">识别把握：{Math.round(draft.confidence * 100)}%</p>}
      {draft?.warnings && draft.warnings.length > 0 && (
        <ul className="warning-list">{draft.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
      )}
      <MealTypeChips value={mealType} onChange={setMealType} />
      <label>时间<input type="datetime-local" value={eatenAt} onChange={(e) => setEatenAt(e.target.value)} required /></label>
      <FoodItemsEditor items={items} onChange={setItems} prefs={prefs} />
      {!draft && <NutritionCard items={items} note="按你填写的数值合计；修改份量会按比例换算。" />}
      <details className="more" open={Boolean(notes)}>
        <summary>备注（可选）</summary>
        <label>备注<textarea value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} /></label>
      </details>
      <button type="submit" disabled={busy}>{busy ? "保存中…" : draft ? "确认并记录" : "保存"}</button>
      {initial && <button type="button" className="ghost-danger" disabled={busy} onClick={() => void remove()}>删除这条记录</button>}
    </form>
  );
}
