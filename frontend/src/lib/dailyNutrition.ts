import type { Meal } from "./health";
import { mealTotals } from "./nutrition";

/** 一天的营养参考值（家庭健康习惯参考，不是医疗建议） */
export type DailyTargets = {
  kcal: number;
  kcalSource: "目标" | "维持参考" | "通用参考";
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
  sugar_max_g: number;
  sodium_max_mg: number;
};

/** 用户在“营养目标”页自己设定的值；为空表示用自动计算的参考值 */
export type TargetOverrides = {
  daily_kcal_target: number | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
  sugar_max_g: number | null;
  sodium_max_mg: number | null;
};

export const NO_OVERRIDES: TargetOverrides = {
  daily_kcal_target: null, protein_g: null, carbs_g: null, fat_g: null, fiber_g: null, sugar_max_g: null, sodium_max_mg: null,
};

export function dailyTargets(opts: { overrides?: TargetOverrides; maintenanceKcal: number | null; weightKg: number | null }): DailyTargets {
  const o = opts.overrides ?? NO_OVERRIDES;
  const kcal = o.daily_kcal_target ?? opts.maintenanceKcal ?? 2000;
  return {
    kcal,
    kcalSource: o.daily_kcal_target ? "目标" : opts.maintenanceKcal ? "维持参考" : "通用参考",
    // 成年人约每公斤体重 1 g；没有体重时按热量的 15%
    protein_g: o.protein_g ?? Math.round(opts.weightKg ? opts.weightKg * 1.0 : (kcal * 0.15) / 4),
    carbs_g: o.carbs_g ?? Math.round((kcal * 0.55) / 4),
    fat_g: o.fat_g ?? Math.round((kcal * 0.25) / 9),
    // 参考《中国居民膳食指南》：膳食纤维 25–30 g，盐 < 5 g（钠约 2000 mg），添加糖 < 50 g
    fiber_g: o.fiber_g ?? 25,
    sugar_max_g: o.sugar_max_g ?? 50,
    sodium_max_mg: o.sodium_max_mg ?? 2000,
  };
}

export type DayIntake = ReturnType<typeof mealTotals> & { meals: number };

export function dayIntake(meals: Meal[]): DayIntake {
  return { ...mealTotals(meals.flatMap((meal) => meal.food_items)), meals: meals.length };
}

export type Tip = { icon: string; text: string };

/** 根据当天已吃的和时间点给 1–3 条简单建议（规则计算，不经过 AI） */
export function intakeTips(intake: DayIntake, targets: DailyTargets, now: Date = new Date()): Tip[] {
  const hour = now.getHours();
  const tips: Tip[] = [];
  if (intake.meals === 0) {
    return [{ icon: "🍽️", text: hour < 10 ? "还没记早餐，吃了什么随手记一笔。" : "今天还没有饮食记录，记一笔就能看到营养分析。" }];
  }
  const kcalLeft = Math.round(targets.kcal - intake.kcal);
  if (kcalLeft < -100) tips.push({ icon: "⚠️", text: `热量已超出${targets.kcalSource} ${-kcalLeft} kcal，后面清淡些，多走走。` });

  const sodium = intake.sodium_mg ?? 0;
  if (sodium > targets.sodium_max_mg) tips.push({ icon: "🧂", text: `钠约 ${Math.round(sodium)} mg，已超过每日上限 ${targets.sodium_max_mg} mg（约 ${(targets.sodium_max_mg / 400).toFixed(1)} g 盐），下一顿少盐少酱。` });
  else if (sodium > targets.sodium_max_mg * 0.75 && hour < 18) tips.push({ icon: "🧂", text: `钠已接近每日上限，晚餐尽量清淡。` });

  const proteinLeft = Math.round(targets.protein_g - (intake.protein_g ?? 0));
  if (hour >= 14 && proteinLeft > targets.protein_g * 0.4) {
    tips.push({ icon: "🥚", text: `蛋白质还差约 ${proteinLeft} g，下一顿可以加鸡蛋、豆腐、鱼虾或瘦肉。` });
  }
  const fiber = intake.fiber_g ?? 0;
  if (hour >= 17 && fiber < targets.fiber_g * 0.5) {
    tips.push({ icon: "🥬", text: `膳食纤维偏少（约 ${Math.round(fiber)} g），多来一份蔬菜或杂粮。` });
  }
  if ((intake.sugar_g ?? 0) > targets.sugar_max_g) tips.push({ icon: "🍬", text: `糖偏多（约 ${Math.round(intake.sugar_g ?? 0)} g），甜饮料和点心先缓一缓。` });

  const fatEnergy = (intake.fat_g ?? 0) * 9;
  if (intake.kcal > 300 && fatEnergy / intake.kcal > 0.35) tips.push({ icon: "🥩", text: "脂肪占比偏高，下一顿少油炸、少肥肉。" });

  if (tips.length === 0) {
    tips.push(kcalLeft > 0
      ? { icon: "✅", text: `目前搭配不错，距${targets.kcalSource}还有约 ${kcalLeft} kcal。` }
      : { icon: "✅", text: "今天的热量差不多了，搭配也不错。" });
  }
  return tips.slice(0, 3);
}
