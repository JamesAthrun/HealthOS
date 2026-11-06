"use client";

import { FoodPrefButtons, type Sentiment } from "@/lib/foodPrefs";
import type { FoodItemInput } from "@/lib/health";
import { type DraftItem, emptyFoodItem, formatNutrient, NUTRIENTS, OPTIONAL_NUTRIENTS, scaleItem } from "@/lib/nutrition";

type Prefs = {
  find: (name: string) => { sentiment: Sentiment } | undefined;
  toggle: (name: string, sentiment: Sentiment) => void;
};

/** 拍照识别和手动记饮食共用的食物编辑：默认只显示名称、份量、热量，营养素折叠 */
export function FoodItemsEditor({
  items,
  onChange,
  prefs,
}: {
  items: DraftItem[];
  onChange: (items: DraftItem[]) => void;
  prefs?: Prefs;
}) {
  function update(index: number, field: keyof FoodItemInput, value: string) {
    onChange(items.map((item, i) => {
      if (i !== index) return item;
      if (field === "name" || field === "unit") return { ...item, [field]: value };
      if (field === "quantity") return scaleItem(item, Number(value));
      if (OPTIONAL_NUTRIENTS.has(field) && value === "") return { ...item, [field]: null };
      return { ...item, [field]: Number(value) };
    }));
  }

  return (
    <div className="stack">
      {items.map((item, index) => (
        <div className="food-row stack" key={index}>
          <label>
            食物
            <input required maxLength={100} value={item.name} placeholder="例如：米饭" onChange={(e) => update(index, "name", e.target.value)} />
          </label>
          {prefs && <FoodPrefButtons name={item.name} current={prefs.find(item.name)?.sentiment} onToggle={prefs.toggle} />}
          <div className="two-col">
            <label>份量<input type="number" inputMode="decimal" min="0.01" step="0.01" required value={item.quantity} onChange={(e) => update(index, "quantity", e.target.value)} /></label>
            <label>单位<input required maxLength={20} value={item.unit} onChange={(e) => update(index, "unit", e.target.value)} /></label>
          </div>
          <label>
            热量（kcal）
            <input type="number" inputMode="decimal" min="0" step="0.1" required placeholder="0" value={item.kcal || ""} onChange={(e) => update(index, "kcal", e.target.value || "0")} />
          </label>
          <details className="more">
            <summary>
              营养素：蛋白 {formatNutrient(item.protein_g, "g")} · 碳水 {formatNutrient(item.carbs_g, "g")} · 脂肪 {formatNutrient(item.fat_g, "g")}
            </summary>
            <div className="two-col">
              {NUTRIENTS.map(({ key, label, unit }) => (
                <label key={key}>
                  {label}（{unit}）
                  <input
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step={unit === "mg" ? "1" : "0.1"}
                    value={item[key] ?? ""}
                    placeholder={OPTIONAL_NUTRIENTS.has(key) ? "未知" : "0"}
                    onChange={(e) => update(index, key, OPTIONAL_NUTRIENTS.has(key) ? e.target.value : e.target.value || "0")}
                  />
                </label>
              ))}
            </div>
          </details>
          {items.length > 1 && (
            <button type="button" className="text-danger" onClick={() => onChange(items.filter((_, i) => i !== index))}>移除这项</button>
          )}
        </div>
      ))}
      <button type="button" className="secondary" onClick={() => onChange([...items, emptyFoodItem()])}>＋ 再加一种食物</button>
    </div>
  );
}
