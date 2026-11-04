// 与 backend/openapi.yml 中 Sprint 2 的记录 schema 对应。
export type FoodItemInput = {
  name: string;
  quantity: number;
  unit: string;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g?: number | null;
  sugar_g?: number | null;
  sodium_mg?: number | null;
};

export type FoodItem = FoodItemInput & { id: string };

export type Meal = {
  id: string;
  eaten_at: string;
  meal_type: "breakfast" | "lunch" | "dinner" | "snack";
  status: string;
  notes: string | null;
  food_items: FoodItem[];
  created_at: string;
  updated_at: string;
};

export type Exercise = {
  id: string;
  type: string;
  started_at: string;
  minutes: number;
  intensity: "low" | "moderate" | "high";
  steps: number | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type Sleep = {
  id: string;
  started_at: string;
  ended_at: string;
  quality: number;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type DailySummary = {
  date: string;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  meal_count: number;
  exercise_minutes: number;
  steps: number;
  sleep_minutes: number;
  sleep_quality: number | null;
};

export type TodayDashboard = {
  date: string;
  target_kcal: number | null;
  kcal_completion_percent: number | null;
  summary: DailySummary;
};

export type TrendDashboard = {
  from_date: string;
  to_date: string;
  days: DailySummary[];
};

export type WeightLog = {
  id: string;
  measured_on: string;
  weight_kg: number;
  waist_cm: number | null;
  body_fat_pct: number | null;
  notes: string | null;
  warning: string | null;
};

export type WeightPoint = { date: string; weight_kg: number };

export type WeightSummary = {
  initial: WeightPoint | null;
  current: WeightPoint | null;
  target_weight_kg: number | null;
  change_kg: number | null;
  to_target_kg: number | null;
  change_7d_kg: number | null;
  change_30d_kg: number | null;
  bmi: number | null;
  trend: (WeightPoint & { avg_7d_kg: number })[];
  notice: string;
};

/** 带符号的变化量，例如 "+0.4" / "−1.2" / "0" */
export function signedKg(value: number): string {
  if (value === 0) return "0";
  return `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}`;
}

/** 本地日期 yyyy-mm-dd，用于 <input type="date"> */
export function todayLocalDate(): string {
  return toDateTimeLocal(new Date()).slice(0, 10);
}

export function toDateTimeLocal(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

export function localInputToIso(value: string): string {
  return new Date(value).toISOString();
}

export function formatLocalDateTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
