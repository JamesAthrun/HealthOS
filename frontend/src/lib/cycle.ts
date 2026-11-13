import { api } from "./api";

export type CycleFlow = "light" | "medium" | "heavy";
export type CycleSymptom = "cramps" | "bloating" | "headache" | "mood" | "breast_tenderness" | "fatigue" | "acne";
export type CyclePhase = "menstrual" | "follicular" | "ovulation" | "luteal" | "late";

export type CyclePeriod = {
  id: string;
  start_date: string;
  end_date: string | null;
  flow: CycleFlow | null;
  symptoms: CycleSymptom[];
  notes: string | null;
};

export type CycleSummary = {
  has_data: boolean;
  cycle_day: number | null;
  phase: CyclePhase | null;
  in_period: boolean;
  avg_cycle_days: number;
  avg_period_days: number;
  insufficient_data: boolean;
  next_start: string | null;
  next_start_earliest: string | null;
  next_start_latest: string | null;
  days_until_next: number | null;
  late_days: number | null;
  alerts: string[];
  kcal_bonus: number;
  tips: string[];
  notice: string;
};

export type CycleSettings = { tracking_enabled: boolean; share_with_ai: boolean; adjust_targets: boolean };
export type CycleSettingsOut = CycleSettings & { available: boolean };

/** 只在开启了周期记录时读取摘要；未开启时返回 null（不再发注定 404 的请求） */
export async function fetchCycleSummary(): Promise<CycleSummary | null> {
  try {
    const settings = await api<CycleSettingsOut>("/cycle-settings");
    if (!settings.available || !settings.tracking_enabled) return null;
    return await api<CycleSummary>("/cycles/summary");
  } catch {
    return null;
  }
}

// 不展示“易孕期”；排卵日附近只叫“周期中段”
export const PHASE_LABELS: Record<CyclePhase, string> = {
  menstrual: "经期",
  follicular: "经期后",
  ovulation: "周期中段",
  luteal: "经前",
  late: "已推迟",
};

export const FLOW_LABELS: Record<CycleFlow, string> = { light: "少", medium: "中", heavy: "多" };

export const SYMPTOM_LABELS: Record<CycleSymptom, string> = {
  cramps: "痛经",
  bloating: "腹胀",
  headache: "头痛",
  mood: "情绪波动",
  breast_tenderness: "乳房胀痛",
  fatigue: "疲劳",
  acne: "痘痘",
};

/** yyyy-mm-dd → “3月5日” */
export function monthDay(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric" }).format(new Date(`${value}T12:00:00`));
}

/** 看板和周期页共用的一句话状态 */
export function cycleHeadline(summary: CycleSummary): { title: string; detail: string } {
  if (!summary.has_data || summary.cycle_day === null) return { title: "—", detail: "点此记录经期" };
  if (summary.in_period) return { title: `经期第 ${summary.cycle_day} 天`, detail: `平均经期约 ${summary.avg_period_days} 天` };
  if (summary.late_days !== null) return { title: `已推迟 ${summary.late_days} 天`, detail: `周期第 ${summary.cycle_day} 天` };
  const next = summary.next_start ? `预计 ${summary.days_until_next} 天后（${monthDay(summary.next_start)}前后）` : "";
  return { title: `周期第 ${summary.cycle_day} 天`, detail: next };
}
