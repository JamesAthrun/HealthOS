"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import {
  dailyTargets,
  type DailyTargets,
  type DayIntake,
  intakeTips,
  NO_OVERRIDES,
  type TargetOverrides,
} from "@/lib/dailyNutrition";

export type TargetInputs = {
  overrides: TargetOverrides;
  maintenanceKcal: number | null;
  weightLossKcal: number | null;
  weightKg: number | null;
};

/** 读取营养目标、热量参考和最新体重 */
export async function fetchTargetInputs(): Promise<TargetInputs> {
  const [overrides, profile, reference] = await Promise.all([
    api<TargetOverrides>("/nutrition-targets").catch(() => NO_OVERRIDES),
    api<{ weight_kg: number | null }>("/profile").catch(() => null),
    api<{ maintenance_kcal: number; weight_loss_kcal: number | null }>("/profile/kcal-reference").catch(() => null),
  ]);
  return {
    overrides,
    maintenanceKcal: reference?.maintenance_kcal ?? null,
    weightLossKcal: reference?.weight_loss_kcal ?? null,
    weightKg: profile?.weight_kg ?? null,
  };
}

/** 每日参考值（自己设定的优先，其余自动计算）；version 变化时重新读取 */
export function useDailyTargets(version = 0): DailyTargets {
  const [targets, setTargets] = useState<DailyTargets>(() => dailyTargets({ maintenanceKcal: null, weightKg: null }));

  useEffect(() => {
    let active = true;
    fetchTargetInputs().then((inputs) => {
      if (active) setTargets(dailyTargets(inputs));
    });
    return () => { active = false; };
  }, [version]);

  return targets;
}

const COLORS = { kcal: "#2f855a", protein: "#2f855a", carbs: "#d69e2e", fat: "#dd6b20", fiber: "#38a169", sugar: "#d53f8c", sodium: "#718096" };

/** 圆环：已摄入 / 目标热量 */
function KcalRing({ value, target }: { value: number; target: number }) {
  const ratio = target > 0 ? value / target : 0;
  const r = 42;
  const c = 2 * Math.PI * r;
  const over = ratio > 1;
  return (
    <svg viewBox="0 0 100 100" className="kcal-ring" role="img" aria-label={`已摄入 ${Math.round(value)} / ${target} kcal`}>
      <circle cx="50" cy="50" r={r} fill="none" stroke="#edf1ef" strokeWidth="10" />
      <circle
        cx="50" cy="50" r={r} fill="none"
        stroke={over ? "#dd6b20" : COLORS.kcal}
        strokeWidth="10" strokeLinecap="round"
        strokeDasharray={`${Math.min(ratio, 1) * c} ${c}`}
        transform="rotate(-90 50 50)"
      />
      <text x="50" y="48" textAnchor="middle" fontSize="18" fontWeight="700" fill="currentColor">{Math.round(value)}</text>
      <text x="50" y="64" textAnchor="middle" fontSize="9" fill="var(--muted)">/ {target} kcal</text>
    </svg>
  );
}

function Bar({ label, value, target, unit, color, limit = false }: {
  label: string; value: number | null; target: number; unit: string; color: string; limit?: boolean;
}) {
  const v = value ?? 0;
  const ratio = target > 0 ? v / target : 0;
  const warn = limit ? ratio > 1 : false;
  return (
    <div className="nutri-bar">
      <div className="nutri-bar-head">
        <span>{label}</span>
        <small>
          {value === null ? "—" : Math.round(v)}
          {" / "}{limit ? "≤" : ""}{target} {unit}
        </small>
      </div>
      <div className="progress thin">
        <span style={{ width: `${Math.min(ratio, 1) * 100}%`, background: warn ? "var(--danger)" : color }} />
      </div>
    </div>
  );
}

/** 今日营养：热量圆环 + 各营养素进度条 + 简单建议 */
export function TodayNutrition({ intake, targets, showTips = true }: { intake: DayIntake; targets: DailyTargets; showTips?: boolean }) {
  const tips = showTips ? intakeTips(intake, targets) : [];
  return (
    <section className="card stack">
      <div className="page-head">
        <h2>营养摄入</h2>
        <small className="muted">{intake.meals} 餐</small>
      </div>
      <div className="nutri-top">
        <KcalRing value={intake.kcal} target={targets.kcal} />
        <div className="nutri-macros">
          <Bar label="蛋白质" value={intake.protein_g} target={targets.protein_g} unit="g" color={COLORS.protein} />
          <Bar label="碳水" value={intake.carbs_g} target={targets.carbs_g} unit="g" color={COLORS.carbs} />
          <Bar label="脂肪" value={intake.fat_g} target={targets.fat_g} unit="g" color={COLORS.fat} />
        </div>
      </div>
      <div className="nutri-minor">
        <Bar label="膳食纤维" value={intake.fiber_g} target={targets.fiber_g} unit="g" color={COLORS.fiber} />
        <Bar label="糖" value={intake.sugar_g} target={targets.sugar_max_g} unit="g" color={COLORS.sugar} limit />
        <Bar label="钠" value={intake.sodium_mg} target={targets.sodium_max_mg} unit="mg" color={COLORS.sodium} limit />
      </div>
      {tips.length > 0 && (
        <ul className="tip-list">
          {tips.map((tip) => <li key={tip.text}><span aria-hidden="true">{tip.icon}</span>{tip.text}</li>)}
        </ul>
      )}
      <p className="muted">
        {targets.kcalSource === "目标" ? "按你设定的营养目标计算" : `热量按${targets.kcalSource}估算`}，仅供参考。
        {" "}<Link href="/targets/">调整目标 ›</Link>
      </p>
    </section>
  );
}
