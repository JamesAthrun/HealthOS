"use client";

import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import {
  formatLocalDateTime,
  localInputToIso,
  type Meal,
  toDateTimeLocal,
} from "@/lib/health";
import { useMe } from "@/lib/useMe";
import { useConfirm } from "@/lib/confirm";
import { FoodPrefButtons, useFoodPreferences } from "@/lib/foodPrefs";
import { nutritionLine } from "@/lib/nutrition";

type FoodForm = {
  name: string;
  quantity: string;
  unit: string;
  kcal: string;
  protein_g: string;
  carbs_g: string;
  fat_g: string;
  fiber_g: string;
  sugar_g: string;
  sodium_mg: string;
};

const EMPTY_FOOD: FoodForm = {
  name: "",
  quantity: "1",
  unit: "份",
  kcal: "",
  protein_g: "0",
  carbs_g: "0",
  fat_g: "0",
  fiber_g: "",
  sugar_g: "",
  sodium_mg: "",
};

const optional = (value: number | null | undefined) => (value === null || value === undefined ? "" : String(value));
const optionalNumber = (value: string) => (value === "" ? null : Number(value));

const MEAL_LABELS: Record<Meal["meal_type"], string> = {
  breakfast: "早餐",
  lunch: "午餐",
  dinner: "晚餐",
  snack: "加餐",
};

export default function MealsPage() {
  const me = useMe();
  const confirm = useConfirm();
  const [meals, setMeals] = useState<Meal[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [eatenAt, setEatenAt] = useState(toDateTimeLocal(new Date()));
  const [mealType, setMealType] = useState<Meal["meal_type"]>("lunch");
  const [notes, setNotes] = useState("");
  const [foods, setFoods] = useState<FoodForm[]>([{ ...EMPTY_FOOD }]);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const foodPrefs = useFoodPreferences(Boolean(me));

  async function load() {
    try {
      setMeals(await api<Meal[]>("/meals"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "饮食记录加载失败");
    }
  }

  useEffect(() => {
    let active = true;
    api<Meal[]>("/meals")
      .then((data) => { if (active) setMeals(data); })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "饮食记录加载失败"); });
    return () => { active = false; };
  }, []);

  function resetForm() {
    setEditingId(null);
    setEatenAt(toDateTimeLocal(new Date()));
    setMealType("lunch");
    setNotes("");
    setFoods([{ ...EMPTY_FOOD }]);
  }

  function updateFood(index: number, field: keyof FoodForm, value: string) {
    setFoods((current) =>
      current.map((food, foodIndex) => (foodIndex === index ? { ...food, [field]: value } : food)),
    );
  }

  function edit(meal: Meal) {
    setEditingId(meal.id);
    setEatenAt(toDateTimeLocal(meal.eaten_at));
    setMealType(meal.meal_type);
    setNotes(meal.notes ?? "");
    setFoods(
      meal.food_items.map((food) => ({
        name: food.name,
        quantity: String(food.quantity),
        unit: food.unit,
        kcal: String(food.kcal),
        protein_g: String(food.protein_g),
        carbs_g: String(food.carbs_g),
        fat_g: String(food.fat_g),
        fiber_g: optional(food.fiber_g),
        sugar_g: optional(food.sugar_g),
        sodium_mg: optional(food.sodium_mg),
      })),
    );
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    const body = {
      eaten_at: localInputToIso(eatenAt),
      meal_type: mealType,
      notes: notes || null,
      food_items: foods.map((food) => ({
        name: food.name,
        quantity: Number(food.quantity),
        unit: food.unit,
        kcal: Number(food.kcal),
        protein_g: Number(food.protein_g || 0),
        carbs_g: Number(food.carbs_g || 0),
        fat_g: Number(food.fat_g || 0),
        fiber_g: optionalNumber(food.fiber_g),
        sugar_g: optionalNumber(food.sugar_g),
        sodium_mg: optionalNumber(food.sodium_mg),
      })),
    };
    try {
      if (editingId) await api<Meal>(`/meals/${editingId}`, { method: "PATCH", body });
      else await api<Meal>("/meals", { method: "POST", body });
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  async function remove(id: string) {
    if (!(await confirm({ title: "删除这条饮食记录？", message: "删除后无法恢复。", confirmText: "删除", danger: true }))) return;
    try {
      await api(`/meals/${id}`, { method: "DELETE" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    }
  }

  if (!me) return <p>加载中…</p>;

  return (
    <div className="stack">
      <form className="card stack" onSubmit={onSubmit}>
        <h1>{editingId ? "编辑饮食" : "记录饮食"}</h1>
        {error && <p className="error" role="alert">{error}</p>}
        <label>
          时间
          <input type="datetime-local" value={eatenAt} onChange={(e) => setEatenAt(e.target.value)} required />
        </label>
        <label>
          类型
          <select value={mealType} onChange={(e) => setMealType(e.target.value as Meal["meal_type"])}>
            {Object.entries(MEAL_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          备注
          <textarea value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
        </label>
        <h2>食物</h2>
        {foods.map((food, index) => (
          <div className="food-row" key={index}>
            <label>名称<input value={food.name} maxLength={100} onChange={(e) => updateFood(index, "name", e.target.value)} required /></label>
            <label>数量<input type="number" min="0.01" step="0.01" value={food.quantity} onChange={(e) => updateFood(index, "quantity", e.target.value)} required /></label>
            <label>单位<input value={food.unit} maxLength={20} onChange={(e) => updateFood(index, "unit", e.target.value)} required /></label>
            <label>热量 kcal<input type="number" min="0" step="0.1" value={food.kcal} onChange={(e) => updateFood(index, "kcal", e.target.value)} required /></label>
            <label>蛋白质 g<input type="number" min="0" step="0.1" value={food.protein_g} onChange={(e) => updateFood(index, "protein_g", e.target.value)} /></label>
            <label>碳水 g<input type="number" min="0" step="0.1" value={food.carbs_g} onChange={(e) => updateFood(index, "carbs_g", e.target.value)} /></label>
            <label>脂肪 g<input type="number" min="0" step="0.1" value={food.fat_g} onChange={(e) => updateFood(index, "fat_g", e.target.value)} /></label>
            <details className="nutrient-details">
              <summary>更多营养素（可选）</summary>
              <div className="nutrient-inputs">
                <label>膳食纤维 g<input type="number" min="0" step="0.1" placeholder="未知" value={food.fiber_g} onChange={(e) => updateFood(index, "fiber_g", e.target.value)} /></label>
                <label>糖 g<input type="number" min="0" step="0.1" placeholder="未知" value={food.sugar_g} onChange={(e) => updateFood(index, "sugar_g", e.target.value)} /></label>
                <label>钠 mg<input type="number" min="0" step="1" placeholder="未知" value={food.sodium_mg} onChange={(e) => updateFood(index, "sodium_mg", e.target.value)} /></label>
              </div>
            </details>
            {foods.length > 1 && <button type="button" className="secondary" onClick={() => setFoods((current) => current.filter((_, i) => i !== index))}>移除这项</button>}
          </div>
        ))}
        <button type="button" className="secondary" onClick={() => setFoods((current) => [...current, { ...EMPTY_FOOD }])}>添加一种食物</button>
        <button type="submit" disabled={submitting}>{submitting ? "保存中…" : editingId ? "保存修改" : "保存饮食"}</button>
        {editingId && <button type="button" className="secondary" onClick={resetForm}>取消编辑</button>}
      </form>

      <section className="card">
        <h1>最近饮食</h1>
        {foodPrefs.error && <p className="error" role="alert">{foodPrefs.error}</p>}
        {meals.length === 0 ? <p className="muted">还没有饮食记录</p> : meals.map((meal) => (
          <article className="record-card" key={meal.id}>
            <strong>{MEAL_LABELS[meal.meal_type]} · {formatLocalDateTime(meal.eaten_at)}</strong>
            <p className="muted">{nutritionLine(meal.food_items)}</p>
            {meal.food_items.map((food) => (
              <div className="pref-row" key={food.id}>
                <span>{food.name}，{food.quantity} {food.unit}，{food.kcal} kcal</span>
                <FoodPrefButtons name={food.name} current={foodPrefs.find(food.name)?.sentiment} onToggle={foodPrefs.toggle} />
              </div>
            ))}
            {meal.notes && <p className="muted">{meal.notes}</p>}
            <div className="actions">
              <button type="button" className="secondary" onClick={() => edit(meal)}>编辑</button>
              <button type="button" className="danger" onClick={() => void remove(meal.id)}>删除</button>
            </div>
          </article>
        ))}
      </section>
    </div>
  );
}
