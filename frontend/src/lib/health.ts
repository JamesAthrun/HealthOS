// 与 backend/openapi.yml 中 Sprint 2 的记录 schema 对应。
export type FoodItemInput = {
  name: string;
  quantity: number;
  unit: string;
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
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
