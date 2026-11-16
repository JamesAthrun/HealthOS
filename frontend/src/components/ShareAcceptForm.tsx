"use client";

import { type FormEvent, useState } from "react";

import { FoodItemsEditor } from "@/components/FoodItemsEditor";
import { MealTypeChips } from "@/components/forms/MealForm";
import { api } from "@/lib/api";
import { useFoodHistory } from "@/lib/foodHistory";
import { type Message, ratioLabel, scaleItems } from "@/lib/friends";
import { localInputToIso, type Meal, toDateTimeLocal } from "@/lib/health";
import { type DraftItem, estimateItems, needsEstimate, NutritionCard, toFoodItem } from "@/lib/nutrition";
import { useAction } from "@/lib/useAction";

const RATIOS = [0.25, 1 / 3, 0.5, 1];

/** 接受共餐邀请：选自己吃了多少，可再改菜品，保存后记到自己的账户 */
export function ShareAcceptForm({ message, onDone }: { message: Message; onDone: (text: string) => void }) {
  const share = message.share!;
  const history = useFoodHistory();
  const { busy, error, run } = useAction();
  const [ratio, setRatio] = useState(share.ratio);
  const [items, setItems] = useState<DraftItem[]>(() => scaleItems(share.food_items, share.ratio));
  const [eatenAt, setEatenAt] = useState(() => toDateTimeLocal(share.eaten_at));
  const [mealType, setMealType] = useState<Meal["meal_type"]>(share.meal_type);
  const [notes, setNotes] = useState(`和${message.other.display_name}一起吃`);
  const options = RATIOS.some((r) => Math.abs(r - share.ratio) < 0.01) ? RATIOS : [share.ratio, ...RATIOS];

  function chooseRatio(next: number) {
    setRatio(next);
    setItems(scaleItems(share.food_items, next));
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    let toSave = items;
    if (items.some(needsEstimate)) {
      const estimated = await run(async () => {
        toSave = await estimateItems(items);
        setItems(toSave);
      }, "营养估算失败。可以手动填热量后再保存");
      if (!estimated) return;
    }
    const ok = await run(() => api(`/meal-shares/${message.id}/accept`, {
      method: "POST",
      body: {
        ratio,
        eaten_at: localInputToIso(eatenAt),
        meal_type: mealType,
        notes: notes.trim() || null,
        food_items: toSave.map(toFoodItem),
      },
    }), "保存失败，请稍后重试");
    if (ok) onDone("已记到你的饮食记录");
  }

  return (
    <form className="stack" onSubmit={onSubmit}>
      {error && <p className="error" role="alert">{error}</p>}
      {share.photo_count > 0 && (
        <div className="photo-strip">
          {Array.from({ length: share.photo_count }, (_, i) => (
            <div key={i} className="photo-thumb" style={{ backgroundImage: `url(/api/meal-shares/${message.id}/photos/${i}?size=thumb)` }}>
              <a href={`/api/meal-shares/${message.id}/photos/${i}`} target="_blank" rel="noreferrer" aria-label={`查看第 ${i + 1} 张照片`} />
            </div>
          ))}
        </div>
      )}
      <div>
        <span className="field-label">我吃了多少（占整餐）</span>
        <div className="chips" role="group" aria-label="份额">
          {options.map((r) => (
            <button key={r} type="button" aria-pressed={Math.abs(r - ratio) < 0.001} onClick={() => chooseRatio(r)}>
              {ratioLabel(r)}{Math.abs(r - share.ratio) < 0.001 && r !== 1 ? "（建议）" : ""}
            </button>
          ))}
        </div>
      </div>
      <NutritionCard items={items} note="已按份额从整餐换算，可以再改下面每种食物的份量。照片会一起保存。" />
      <MealTypeChips value={mealType} onChange={setMealType} />
      <label>时间<input type="datetime-local" value={eatenAt} onChange={(e) => setEatenAt(e.target.value)} required /></label>
      <FoodItemsEditor items={items} onChange={setItems} history={history} />
      <label>备注<textarea value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} /></label>
      <button type="submit" disabled={busy}>{busy ? "保存中…" : "接受并记录"}</button>
    </form>
  );
}
