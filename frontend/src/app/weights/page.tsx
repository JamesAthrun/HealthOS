"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { RecordTypePage } from "@/components/RecordTypePage";
import { api } from "@/lib/api";
import { signedKg, type WeightLog, type WeightSummary } from "@/lib/health";
import { weightEntry } from "@/lib/records";

const load = async () => (await api<WeightLog[]>("/weights")).map(weightEntry);

export default function WeightsPage() {
  return (
    <RecordTypePage
      title="体重"
      kind="weight"
      load={load}
      emptyText="还没有体重记录，点右下角“＋ 记体重”记录今天的体重。"
      top={(version) => <SummaryLoader version={version} />}
    />
  );
}

function SummaryLoader({ version }: { version: number }) {
  const [summary, setSummary] = useState<WeightSummary | null>(null);

  useEffect(() => {
    let active = true;
    api<WeightSummary>("/weights/summary")
      .then((data) => { if (active) setSummary(data); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [version]);

  if (!summary?.current) return null;
  return <SummaryCard summary={summary} />;
}

function SummaryCard({ summary }: { summary: WeightSummary }) {
  const current = summary.current!;
  return (
    <section className="card stack">
      <div>
        <p className="eyebrow">当前体重</p>
        <p className="big-number">{current.weight_kg} <small>kg</small></p>
        <p className="muted">最近一次：{current.date}</p>
      </div>
      <div className="metric-grid">
        <article className="metric">
          <span>比初始</span>
          <strong>{summary.change_kg === null ? "—" : signedKg(summary.change_kg)} <small>kg</small></strong>
          <small>初始 {summary.initial?.weight_kg} kg · {summary.initial?.date}</small>
        </article>
        <article className="metric">
          <span>距目标</span>
          <strong>{summary.to_target_kg === null ? "—" : signedKg(summary.to_target_kg)} <small>kg</small></strong>
          <small>{summary.target_weight_kg ? `目标 ${summary.target_weight_kg} kg` : "尚未设置目标体重"}</small>
        </article>
        <article className="metric">
          <span>近 7 天</span>
          <strong>{summary.change_7d_kg === null ? "—" : signedKg(summary.change_7d_kg)} <small>kg</small></strong>
          <small>近 30 天 {summary.change_30d_kg === null ? "—" : `${signedKg(summary.change_30d_kg)} kg`}</small>
        </article>
        <article className="metric">
          <span>BMI</span>
          <strong>{summary.bmi ?? "—"}</strong>
          <small>{summary.bmi ? "18.5–23.9 为常用参考区间" : "填写身高后计算"}</small>
        </article>
      </div>
      {summary.trend.length >= 2 && <WeightChart points={summary.trend} target={summary.target_weight_kg} />}
      <small className="muted">{summary.notice}</small>
      <Link href="/profile/">{summary.target_weight_kg ? "修改目标体重" : "设置目标体重"}</Link>
    </section>
  );
}

/** 最近 30 天：圆点是每次记录，线是 7 天平均；虚线是目标体重（在范围内时）。 */
function WeightChart({ points, target }: { points: WeightSummary["trend"]; target: number | null }) {
  const width = 320;
  const height = 140;
  const pad = 12;
  const days = (iso: string) => new Date(`${iso}T12:00:00`).getTime() / 86_400_000;
  const x0 = days(points[0].date);
  const span = Math.max(days(points[points.length - 1].date) - x0, 1);
  const values = points.flatMap((p) => [p.weight_kg, p.avg_7d_kg]);
  const min = Math.min(...values) - 0.5;
  const max = Math.max(...values) + 0.5;
  const x = (iso: string) => pad + ((days(iso) - x0) / span) * (width - pad * 2);
  const y = (kg: number) => pad + ((max - kg) / (max - min)) * (height - pad * 2);
  const avgPath = points.map((p, i) => `${i ? "L" : "M"}${x(p.date).toFixed(1)},${y(p.avg_7d_kg).toFixed(1)}`).join(" ");

  return (
    <figure className="stack">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="最近 30 天体重趋势" style={{ width: "100%", height: "auto" }}>
        {target !== null && target >= min && target <= max && (
          <line x1={pad} x2={width - pad} y1={y(target)} y2={y(target)} stroke="var(--muted)" strokeDasharray="4 4" />
        )}
        <path d={avgPath} fill="none" stroke="var(--primary)" strokeWidth="2" />
        {points.map((p) => (
          <circle key={p.date} cx={x(p.date)} cy={y(p.weight_kg)} r="3" fill="var(--primary)" opacity="0.5" />
        ))}
      </svg>
      <figcaption className="muted">
        最近 30 天 · 圆点为每次记录，曲线为 7 天平均{target !== null && "，虚线为目标"}（{min.toFixed(1)}–{max.toFixed(1)} kg）
      </figcaption>
    </figure>
  );
}
