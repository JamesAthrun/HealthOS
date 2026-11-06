import type { FoodItemInput } from "@/lib/health";

type NutrientKey = "protein_g" | "carbs_g" | "fat_g" | "fiber_g" | "sugar_g" | "sodium_mg";

export const NUTRIENTS: { key: NutrientKey; label: string; unit: string }[] = [
  { key: "protein_g", label: "蛋白质", unit: "g" },
  { key: "carbs_g", label: "碳水", unit: "g" },
  { key: "fat_g", label: "脂肪", unit: "g" },
  { key: "fiber_g", label: "膳食纤维", unit: "g" },
  { key: "sugar_g", label: "糖", unit: "g" },
  { key: "sodium_mg", label: "钠", unit: "mg" },
];

/** 可以留空（未知）的营养素 */
export const OPTIONAL_NUTRIENTS = new Set<string>(["fiber_g", "sugar_g", "sodium_mg"]);

type Totals = { kcal: number } & Record<NutrientKey, number | null>;

export function mealTotals(items: FoodItemInput[]): Totals {
  const totals: Totals = { kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: null, sugar_g: null, sodium_mg: null };
  for (const item of items) {
    totals.kcal += item.kcal || 0;
    for (const { key } of NUTRIENTS) {
      const value = item[key];
      if (value === null || value === undefined || Number.isNaN(value)) continue;
      totals[key] = (totals[key] ?? 0) + value;
    }
  }
  return totals;
}

export function formatNutrient(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined) return "—";
  return unit === "mg" ? `${Math.round(value)} mg` : `${Math.round(value * 10) / 10} g`;
}

/** 一行摘要，用于饮食记录列表 */
export function nutritionLine(items: FoodItemInput[]): string {
  const t = mealTotals(items);
  const parts = [
    `${Math.round(t.kcal)} kcal`,
    `蛋白 ${formatNutrient(t.protein_g, "g")}`,
    `碳水 ${formatNutrient(t.carbs_g, "g")}`,
    `脂肪 ${formatNutrient(t.fat_g, "g")}`,
  ];
  if (t.sodium_mg !== null) parts.push(`钠 ${formatNutrient(t.sodium_mg, "mg")}`);
  return parts.join(" · ");
}

/** 份量改变时按比例换算热量和营养素；份量暂时无效（清空正在输入）时保留原值等下次换算 */
export type DraftItem = FoodItemInput & { baseQuantity?: number };

export function emptyFoodItem(): DraftItem {
  return { name: "", quantity: 1, unit: "份", kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: null, sugar_g: null, sodium_mg: null };
}

export function scaleItem(item: DraftItem, quantity: number): DraftItem {
  const from = item.quantity > 0 ? item.quantity : item.baseQuantity ?? 0;
  if (!(quantity > 0) || !(from > 0)) return { ...item, quantity, baseQuantity: from || undefined };
  const ratio = quantity / from;
  const scaled: DraftItem = { ...item, quantity, baseQuantity: undefined, kcal: round1(item.kcal * ratio) };
  for (const { key } of NUTRIENTS) {
    const value = item[key];
    if (typeof value === "number") scaled[key] = round1(value * ratio);
  }
  return scaled;
}

/** 提交前去掉只在草稿里使用的字段（后端不接受多余字段） */
export function toFoodItem(item: DraftItem): FoodItemInput {
  const copy = { ...item };
  delete copy.baseQuantity;
  return copy;
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

const MACRO_COLORS = { protein_g: "#2f855a", carbs_g: "#d69e2e", fat_g: "#dd6b20" } as const;

export function NutritionCard({
  items,
  note = "AI 根据照片粗略估算，仅供参考；钠和糖受调料、酱汁影响大。修改份量会按比例换算热量和营养素。",
}: { items: FoodItemInput[]; note?: string }) {
  const t = mealTotals(items);
  const energy = {
    protein_g: (t.protein_g ?? 0) * 4,
    carbs_g: (t.carbs_g ?? 0) * 4,
    fat_g: (t.fat_g ?? 0) * 9,
  };
  const energyTotal = energy.protein_g + energy.carbs_g + energy.fat_g;
  const share = (key: keyof typeof energy) => (energyTotal > 0 ? Math.round((energy[key] / energyTotal) * 100) : 0);

  return (
    <div className="nutrition-card stack">
      <div className="nutrition-head">
        <span>本餐营养估算</span>
        <strong>{Math.round(t.kcal)} <small>kcal</small></strong>
      </div>
      {energyTotal > 0 && (
        <div className="macro-bar" aria-label="三大营养素供能比">
          {(Object.keys(MACRO_COLORS) as (keyof typeof MACRO_COLORS)[]).map((key) => (
            <span key={key} style={{ width: `${share(key)}%`, background: MACRO_COLORS[key] }} />
          ))}
        </div>
      )}
      <div className="nutrient-grid">
        {NUTRIENTS.map(({ key, label, unit }) => (
          <div key={key}>
            <small>
              {key in MACRO_COLORS && <i style={{ background: MACRO_COLORS[key as keyof typeof MACRO_COLORS] }} />}
              {label}
            </small>
            <strong>{formatNutrient(t[key], unit)}</strong>
            {key in MACRO_COLORS && energyTotal > 0 && <small>{share(key as keyof typeof energy)}% 热量</small>}
          </div>
        ))}
      </div>
      <p className="muted">{note}</p>
    </div>
  );
}
