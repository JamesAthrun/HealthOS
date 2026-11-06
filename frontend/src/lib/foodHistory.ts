"use client";

import { useEffect, useState } from "react";

import { api } from "./api";
import { normalizeFoodName } from "./foodPrefs";
import type { FoodItemInput, Meal } from "./health";
import type { DraftItem } from "./nutrition";

/** 自己吃过的食物：同名取最近一次的记录，用来一键填好热量和营养素（不需要 AI） */
export type FoodHistory = { names: string[]; lookup: (name: string) => FoodItemInput | undefined };

const EMPTY: FoodHistory = { names: [], lookup: () => undefined };

export function useFoodHistory(): FoodHistory {
  const [history, setHistory] = useState<FoodHistory>(EMPTY);

  useEffect(() => {
    let active = true;
    api<Meal[]>("/meals")
      .then((meals) => {
        const byName = new Map<string, FoodItemInput>();
        for (const meal of meals) {
          for (const food of meal.food_items) {
            const key = normalizeFoodName(food.name);
            // 列表按时间倒序，第一次出现的就是最近一次；没有热量的记录没有参考价值
            if (key && food.kcal > 0 && !byName.has(key)) byName.set(key, food);
          }
        }
        if (active) {
          setHistory({
            names: [...byName.values()].map((food) => food.name),
            lookup: (name) => byName.get(normalizeFoodName(name)),
          });
        }
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  return history;
}

/** 用历史记录填好这一项；单位相同按份量换算，单位不同就沿用历史的份量和单位 */
export function fillFromHistory(item: DraftItem, past: FoodItemInput): DraftItem {
  const sameUnit = past.unit === item.unit && item.quantity > 0;
  const ratio = sameUnit ? item.quantity / past.quantity : 1;
  const scale = (value: number | null | undefined) => (value == null ? null : Math.round(value * ratio * 10) / 10);
  return {
    ...item,
    name: past.name,
    quantity: sameUnit ? item.quantity : past.quantity,
    unit: past.unit,
    kcal: scale(past.kcal) ?? 0,
    protein_g: scale(past.protein_g) ?? 0,
    carbs_g: scale(past.carbs_g) ?? 0,
    fat_g: scale(past.fat_g) ?? 0,
    fiber_g: scale(past.fiber_g),
    sugar_g: scale(past.sugar_g),
    sodium_mg: scale(past.sodium_mg),
    baseQuantity: undefined,
    stale: false,
  };
}
