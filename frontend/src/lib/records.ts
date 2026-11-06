import { api } from "./api";
import type { Exercise, Meal, Sleep, WeightLog } from "./health";
import { toDateTimeLocal } from "./health";

export const MEAL_LABELS: Record<Meal["meal_type"], string> = {
  breakfast: "早餐",
  lunch: "午餐",
  dinner: "晚餐",
  snack: "加餐",
};

export const INTENSITY_LABELS: Record<Exercise["intensity"], string> = { low: "低", moderate: "中", high: "高" };

export const QUALITY_LABELS: Record<number, string> = { 1: "很差", 2: "较差", 3: "一般", 4: "较好", 5: "很好" };

export type RecordKind = "meal" | "exercise" | "sleep" | "weight";

export const KIND_META: Record<RecordKind, { icon: string; label: string }> = {
  meal: { icon: "🍚", label: "饮食" },
  exercise: { icon: "🏃", label: "运动" },
  sleep: { icon: "😴", label: "睡眠" },
  weight: { icon: "⚖️", label: "体重" },
};

/** 本地日期 yyyy-mm-dd */
export function dayKey(value: string | Date): string {
  return toDateTimeLocal(value).slice(0, 10);
}

export function shiftDay(key: string, delta: number): string {
  const date = new Date(`${key}T12:00:00`);
  date.setDate(date.getDate() + delta);
  return dayKey(date);
}

/** “今天 / 昨天 / 11月4日 周二” */
export function dayLabel(key: string): string {
  const today = dayKey(new Date());
  if (key === today) return "今天";
  if (key === shiftDay(today, -1)) return "昨天";
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "short" }).format(
    new Date(`${key}T12:00:00`),
  );
}

export function timeOf(iso: string): string {
  return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

export function sleepMinutes(row: Sleep): number {
  return Math.round((new Date(row.ended_at).getTime() - new Date(row.started_at).getTime()) / 60_000);
}

export function formatMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h} 小时${m ? ` ${m} 分` : ""}` : `${m} 分钟`;
}

export function mealKcal(meal: Meal): number {
  return Math.round(meal.food_items.reduce((sum, food) => sum + food.kcal, 0));
}

/** 按本地日期分组（保持原有顺序） */
export function groupByDay<T>(rows: T[], dateOf: (row: T) => string): { key: string; rows: T[] }[] {
  const groups: { key: string; rows: T[] }[] = [];
  for (const row of rows) {
    const key = dateOf(row);
    const last = groups[groups.length - 1];
    if (last?.key === key) last.rows.push(row);
    else groups.push({ key, rows: [row] });
  }
  return groups;
}

export type AllRecords = { meals: Meal[]; exercises: Exercise[]; sleeps: Sleep[]; weights: WeightLog[] };

export async function fetchAllRecords(): Promise<AllRecords> {
  const [meals, exercises, sleeps, weights] = await Promise.all([
    api<Meal[]>("/meals"),
    api<Exercise[]>("/exercises"),
    api<Sleep[]>("/sleeps"),
    api<WeightLog[]>("/weights?limit=60"),
  ]);
  return { meals, exercises, sleeps, weights };
}

type EntryBase = { id: string; day: string; sortAt: string; title: string; detail: string; side: string };
export type Entry =
  | (EntryBase & { kind: "meal"; row: Meal })
  | (EntryBase & { kind: "exercise"; row: Exercise })
  | (EntryBase & { kind: "sleep"; row: Sleep })
  | (EntryBase & { kind: "weight"; row: WeightLog });

export function mealEntry(row: Meal): Entry {
  return {
    kind: "meal", id: row.id, row, day: dayKey(row.eaten_at), sortAt: row.eaten_at,
    title: `${MEAL_LABELS[row.meal_type]} · ${row.food_items.map((f) => f.name).join("、")}`,
    detail: timeOf(row.eaten_at),
    side: `${mealKcal(row)} kcal`,
  };
}

export function exerciseEntry(row: Exercise): Entry {
  return {
    kind: "exercise", id: row.id, row, day: dayKey(row.started_at), sortAt: row.started_at,
    title: row.type,
    detail: `${timeOf(row.started_at)} · ${INTENSITY_LABELS[row.intensity]}强度${row.steps ? ` · ${row.steps} 步` : ""}`,
    side: `${row.minutes} 分钟`,
  };
}

/** 睡眠算在醒来那天 */
export function sleepEntry(row: Sleep): Entry {
  return {
    kind: "sleep", id: row.id, row, day: dayKey(row.ended_at), sortAt: row.ended_at,
    title: `睡眠 · ${QUALITY_LABELS[row.quality]}`,
    detail: `${timeOf(row.started_at)} – ${timeOf(row.ended_at)}`,
    side: formatMinutes(sleepMinutes(row)),
  };
}

export function weightEntry(row: WeightLog): Entry {
  return {
    kind: "weight", id: row.id, row, day: row.measured_on, sortAt: `${row.measured_on}T00:00:00`,
    title: "体重",
    detail: [row.waist_cm !== null && `腰围 ${row.waist_cm} cm`, row.body_fat_pct !== null && `体脂 ${row.body_fat_pct}%`]
      .filter(Boolean).join(" · ") || (row.notes ?? ""),
    side: `${row.weight_kg} kg`,
  };
}

/** 某一天的所有记录，按时间排序 */
export function entriesForDay(all: AllRecords, key: string): Entry[] {
  return [
    ...all.meals.map(mealEntry),
    ...all.exercises.map(exerciseEntry),
    ...all.sleeps.map(sleepEntry),
    ...all.weights.map(weightEntry),
  ]
    .filter((entry) => entry.day === key)
    .sort((a, b) => new Date(a.sortAt).getTime() - new Date(b.sortAt).getTime());
}

/** 给定日期的默认时间：今天用现在，其他日期用当天的 hh:mm */
export function defaultDateTime(day: string | undefined, hhmm: string): string {
  if (!day || day === dayKey(new Date())) return toDateTimeLocal(new Date());
  return `${day}T${hhmm}`;
}
