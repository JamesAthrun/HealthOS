"use client";

import { type ComponentProps, useId, useState } from "react";

import { fillFromHistory, type FoodHistory } from "@/lib/foodHistory";
import { FoodPrefButtons, type Sentiment } from "@/lib/foodPrefs";
import type { FoodItemInput } from "@/lib/health";
import {
  type DraftItem,
  emptyFoodItem,
  estimateItems,
  formatNutrient,
  needsEstimate,
  NUTRIENTS,
  OPTIONAL_NUTRIENTS,
  scaleItem,
} from "@/lib/nutrition";
import { useAction } from "@/lib/useAction";

/** 数字输入：保留用户正在输入的文本，清空时不会被立刻填回 0 */
function NumberInput({ value, onText, ...props }: { value: number | null | undefined; onText: (text: string) => void } & Omit<ComponentProps<"input">, "value" | "onChange" | "type">) {
  const external = value ?? null;
  const [text, setText] = useState(external === null || external === 0 ? "" : String(external));
  const [prev, setPrev] = useState(external);
  // 只在外部数值真的变了（例如估算、按历史填写）时才覆盖输入框
  if (external !== prev) {
    setPrev(external);
    const parsed = text === "" ? null : Number(text);
    if (parsed !== external && !(parsed === null && external === 0)) setText(external === null ? "" : String(external));
  }
  return <input {...props} type="number" inputMode="decimal" value={text} onChange={(e) => { setText(e.target.value); onText(e.target.value); }} />;
}

type Prefs = {
  find: (name: string) => { sentiment: Sentiment } | undefined;
  toggle: (name: string, sentiment: Sentiment) => void;
};

/**
 * 拍照、文字、直接填写和编辑共用的食物编辑。
 * 只需要填“吃了什么、吃了多少”：热量和营养素可以用吃过的记录一键填好，或点“估算营养”交给 AI。
 */
export function FoodItemsEditor({
  items,
  onChange,
  prefs,
  history,
}: {
  items: DraftItem[];
  onChange: (items: DraftItem[]) => void;
  prefs?: Prefs;
  history?: FoodHistory;
}) {
  const listId = useId();
  const { busy, error, run } = useAction();
  const pending = items.filter(needsEstimate).length;

  function update(index: number, field: keyof FoodItemInput, value: string) {
    onChange(items.map((item, i) => {
      if (i !== index) return item;
      if (field === "name") {
        const past = history?.lookup(value);
        // 选中了吃过的食物：直接用上次的数值，不用再估算
        if (past && past.name === value) return fillFromHistory(item, past);
        return { ...item, name: value, stale: true };
      }
      if (field === "unit") return { ...item, unit: value, stale: true };
      if (field === "quantity") return scaleItem(item, Number(value));
      // 手动改了热量，视为用户自己给出了数值
      if (field === "kcal") return { ...item, kcal: Number(value), stale: false };
      if (OPTIONAL_NUTRIENTS.has(field) && value === "") return { ...item, [field]: null };
      return { ...item, [field]: Number(value) };
    }));
  }

  async function estimate() {
    await run(async () => onChange(await estimateItems(items)), "营养估算失败，请稍后重试");
  }

  return (
    <div className="stack">
      {history && history.names.length > 0 && (
        <datalist id={listId}>
          {history.names.map((name) => <option key={name} value={name} />)}
        </datalist>
      )}
      {items.map((item, index) => (
        <div className="food-row stack" key={index}>
          <label>
            食物
            <input
              required
              maxLength={100}
              value={item.name}
              list={history?.names.length ? listId : undefined}
              placeholder="例如：米饭、番茄炒蛋"
              onChange={(e) => update(index, "name", e.target.value)}
            />
          </label>
          {prefs && <FoodPrefButtons name={item.name} current={prefs.find(item.name)?.sentiment} onToggle={prefs.toggle} />}
          <div className="two-col">
            <label>份量<NumberInput min="0.01" step="0.01" required value={item.quantity} onText={(text) => update(index, "quantity", text)} /></label>
            <label>单位<input required maxLength={20} value={item.unit} placeholder="碗、个、g" onChange={(e) => update(index, "unit", e.target.value)} /></label>
          </div>
          {needsEstimate(item) ? (
            <p className="muted">{item.kcal > 0 ? "名称或单位改了，点下方“估算营养”更新数值" : "热量和营养素：点下方“估算营养”自动填写"}</p>
          ) : (
            <>
              <dl className="item-nutrients" aria-label={`${item.name || "这项食物"}的营养`}>
                <div><dt>热量</dt><dd>{Math.round(item.kcal)} kcal</dd></div>
                {NUTRIENTS.map(({ key, label, unit }) => (
                  <div key={key}><dt>{label}</dt><dd>{formatNutrient(item[key], unit)}</dd></div>
                ))}
              </dl>
              <details className="more">
                <summary>修改数值</summary>
                <div className="two-col">
                <label>
                  热量（kcal）
                  <NumberInput min="0" step="0.1" placeholder="0" value={item.kcal} onText={(text) => update(index, "kcal", text || "0")} />
                </label>
                {NUTRIENTS.map(({ key, label, unit }) => (
                  <label key={key}>
                    {label}（{unit}）
                    <NumberInput
                      min="0"
                      step={unit === "mg" ? "1" : "0.1"}
                      value={item[key]}
                      placeholder={OPTIONAL_NUTRIENTS.has(key) ? "未知" : "0"}
                      onText={(text) => update(index, key, OPTIONAL_NUTRIENTS.has(key) ? text : text || "0")}
                    />
                  </label>
                ))}
                </div>
              </details>
            </>
          )}
          {items.length > 1 && (
            <button type="button" className="text-danger" onClick={() => onChange(items.filter((_, i) => i !== index))}>移除这项</button>
          )}
        </div>
      ))}
      {error && <p className="error" role="alert">{error}</p>}
      {pending > 0 && (
        <button type="button" disabled={busy} onClick={() => void estimate()}>
          {busy ? "估算中…" : `✨ 估算营养${pending > 1 ? `（${pending} 项）` : ""}`}
        </button>
      )}
      <button type="button" className="secondary" onClick={() => onChange([...items, emptyFoodItem()])}>＋ 再加一种食物</button>
      {history && history.names.length > 0 && <p className="muted">输入名称时会提示你吃过的食物，选中即可直接填好数值。</p>}
    </div>
  );
}
