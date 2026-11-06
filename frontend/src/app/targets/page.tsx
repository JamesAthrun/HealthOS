"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { fetchTargetInputs, type TargetInputs } from "@/components/TodayNutrition";
import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import { dailyTargets, NO_OVERRIDES, type TargetOverrides } from "@/lib/dailyNutrition";
import { useToast } from "@/lib/toast";
import { useAction } from "@/lib/useAction";
import { useMe } from "@/lib/useMe";

type Key = keyof TargetOverrides;
type Form = Record<Key, string>;

const FIELDS: { key: Key; label: string; unit: string; step: string; group: "kcal" | "macro" | "limit"; hint?: string }[] = [
  { key: "daily_kcal_target", label: "每日热量", unit: "kcal", step: "10", group: "kcal" },
  { key: "protein_g", label: "蛋白质", unit: "g", step: "1", group: "macro", hint: "默认约每公斤体重 1 g" },
  { key: "carbs_g", label: "碳水", unit: "g", step: "1", group: "macro", hint: "默认占热量 55%" },
  { key: "fat_g", label: "脂肪", unit: "g", step: "1", group: "macro", hint: "默认占热量 25%" },
  { key: "fiber_g", label: "膳食纤维（至少）", unit: "g", step: "1", group: "limit" },
  { key: "sugar_max_g", label: "糖（最多）", unit: "g", step: "1", group: "limit" },
  { key: "sodium_max_mg", label: "钠（最多）", unit: "mg", step: "50", group: "limit", hint: "1 g 盐约含 400 mg 钠" },
];

const toForm = (o: TargetOverrides): Form =>
  Object.fromEntries(FIELDS.map(({ key }) => [key, o[key] == null ? "" : String(o[key])])) as Form;

const toOverrides = (f: Form): TargetOverrides =>
  Object.fromEntries(FIELDS.map(({ key }) => [key, f[key] === "" ? null : Number(f[key])])) as TargetOverrides;

export default function TargetsPage() {
  const me = useMe();
  const toast = useToast();
  const confirm = useConfirm();
  const { busy, error, run } = useAction();
  const [inputs, setInputs] = useState<TargetInputs | null>(null);
  const [form, setForm] = useState<Form>(toForm(NO_OVERRIDES));

  useEffect(() => {
    if (!me) return;
    let active = true;
    fetchTargetInputs().then((next) => {
      if (!active) return;
      setInputs(next);
      setForm(toForm(next.overrides));
    });
    return () => { active = false; };
  }, [me]);

  if (!me || !inputs) return <p className="muted">加载中…</p>;

  // 默认值随当前填写的热量变化（碳水、脂肪按热量比例）
  const kcalOverride = form.daily_kcal_target === "" ? null : Number(form.daily_kcal_target);
  const defaults = dailyTargets({ ...inputs, overrides: { ...NO_OVERRIDES, daily_kcal_target: kcalOverride } });
  const autoKcal = inputs.maintenanceKcal ?? 2000;
  const defaultOf = (key: Key) => (key === "daily_kcal_target" ? autoKcal : defaults[key]);

  async function save(next: TargetOverrides, message: string) {
    const ok = await run(async () => {
      const saved = await api<TargetOverrides>("/nutrition-targets", { method: "PUT", body: next });
      setForm(toForm(saved));
    }, "保存失败，请检查数值范围");
    if (ok) toast(message);
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    await save(toOverrides(form), "营养目标已保存");
  }

  async function reset() {
    if (!(await confirm({ title: "全部恢复默认？", message: "清空你设定的目标，改用自动计算的参考值。", confirmText: "恢复默认" }))) return;
    await save(NO_OVERRIDES, "已恢复默认");
  }

  function field(key: Key) {
    const meta = FIELDS.find((f) => f.key === key)!;
    return (
      <label key={key}>
        {meta.label}（{meta.unit}）
        <input
          type="number"
          inputMode="decimal"
          step={meta.step}
          min="0"
          value={form[key]}
          placeholder={`默认 ${Math.round(defaultOf(key))}`}
          onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        />
        <small className="muted">
          {form[key] === "" ? meta.hint ?? "留空即使用默认值" : `默认 ${Math.round(defaultOf(key))}${meta.hint ? ` · ${meta.hint}` : ""}`}
        </small>
      </label>
    );
  }

  return (
    <form className="stack" onSubmit={onSubmit}>
      <div>
        <h1>营养目标</h1>
        <p className="muted">首页的营养摄入和建议按这里的目标计算。留空的项目使用自动计算的参考值。</p>
      </div>
      {error && <p className="error" role="alert">{error}</p>}

      <section className="card stack">
        <h2>每日热量</h2>
        {field("daily_kcal_target")}
        {inputs.maintenanceKcal ? (
          <div className="chips">
            <button type="button" onClick={() => setForm({ ...form, daily_kcal_target: String(inputs.maintenanceKcal) })}>
              维持体重 {inputs.maintenanceKcal}
            </button>
            {inputs.weightLossKcal && (
              <button type="button" onClick={() => setForm({ ...form, daily_kcal_target: String(inputs.weightLossKcal) })}>
                温和减重 {inputs.weightLossKcal}
              </button>
            )}
          </div>
        ) : (
          <p className="muted">在 <Link href="/profile/">健康档案</Link> 填好出生年份、性别、身高和活动水平，并记录体重后，可以看到维持和减重的参考热量。</p>
        )}
      </section>

      <section className="card stack">
        <h2>三大营养素</h2>
        {field("protein_g")}
        {field("carbs_g")}
        {field("fat_g")}
      </section>

      <section className="card stack">
        <h2>每日限量</h2>
        {field("fiber_g")}
        {field("sugar_max_g")}
        {field("sodium_max_mg")}
      </section>

      <button type="submit" disabled={busy}>{busy ? "保存中…" : "保存"}</button>
      <button type="button" className="secondary" disabled={busy} onClick={() => void reset()}>全部恢复默认</button>
      <p className="muted">默认值参考《中国居民膳食指南》，仅作健康习惯参考；如有慢性病或特殊饮食要求，请遵医嘱设定。</p>
    </form>
  );
}
