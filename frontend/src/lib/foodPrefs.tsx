"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";

export type Sentiment = "like" | "dislike";
type Preference = { id: string; food_name: string; sentiment: Sentiment; updated_at: string };

/** 与后端 normalize_food_name 保持一致：NFKC、合并空白、去首尾空格、英文小写 */
export function normalizeFoodName(name: string): string {
  return name.normalize("NFKC").replace(/\s+/g, " ").trim().toLowerCase();
}

export function useFoodPreferences(enabled: boolean) {
  const [prefs, setPrefs] = useState<Preference[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!enabled) return;
    api<Preference[]>("/food-preferences").then(setPrefs).catch(() => setError("食物偏好加载失败"));
  }, [enabled]);

  const find = useCallback(
    (name: string) => prefs.find((p) => p.food_name === normalizeFoodName(name)),
    [prefs],
  );

  /** 点击当前已选中的状态会取消（删除）；否则设置为新状态 */
  const toggle = useCallback(async (name: string, sentiment: Sentiment) => {
    setError("");
    const existing = prefs.find((p) => p.food_name === normalizeFoodName(name));
    try {
      if (existing?.sentiment === sentiment) {
        await api(`/food-preferences/${existing.id}`, { method: "DELETE" });
        setPrefs((current) => current.filter((p) => p.id !== existing.id));
      } else {
        const saved = await api<Preference>("/food-preferences", {
          method: "PUT",
          body: { food_name: name, sentiment },
        });
        setPrefs((current) => [saved, ...current.filter((p) => p.id !== saved.id)]);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存失败");
    }
  }, [prefs]);

  const remove = useCallback(async (id: string) => {
    setError("");
    try {
      await api(`/food-preferences/${id}`, { method: "DELETE" });
      setPrefs((current) => current.filter((p) => p.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    }
  }, []);

  return { prefs, find, toggle, remove, error };
}

export function FoodPrefButtons({
  name,
  current,
  onToggle,
}: {
  name: string;
  current: Sentiment | undefined;
  onToggle: (name: string, sentiment: Sentiment) => void;
}) {
  if (!normalizeFoodName(name)) return null;
  return (
    <span className="pref-buttons" aria-label={`对“${name}”的偏好`}>
      <button type="button" aria-pressed={current === "like"} onClick={() => onToggle(name, "like")}>
        喜欢
      </button>
      <button type="button" aria-pressed={current === "dislike"} onClick={() => onToggle(name, "dislike")}>
        不想再吃
      </button>
    </span>
  );
}
