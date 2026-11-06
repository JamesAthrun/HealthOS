"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EntryList, entryTarget, newTarget, useRecordSheet } from "@/components/EntryList";
import { RecordSheet } from "@/components/RecordSheet";
import { api, ApiError } from "@/lib/api";
import { signedKg, type TodayDashboard, type TrendDashboard, type WeightSummary } from "@/lib/health";
import { type AllRecords, dayKey, entriesForDay, fetchAllRecords, QUALITY_LABELS } from "@/lib/records";
import { useMe } from "@/lib/useMe";

type HomeData = { today: TodayDashboard; trends: TrendDashboard; weight: WeightSummary | null; records: AllRecords };

async function fetchHome(): Promise<HomeData> {
  const [today, trends, weight, records] = await Promise.all([
    api<TodayDashboard>("/dashboard/today"),
    api<TrendDashboard>("/dashboard/trends?days=7"),
    api<WeightSummary>("/weights/summary").catch(() => null),
    fetchAllRecords(),
  ]);
  return { today, trends, weight, records };
}

export default function HomePage() {
  const me = useMe();
  const [data, setData] = useState<HomeData | null>(null);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    try {
      setData(await fetchHome());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败，请稍后重试");
    }
  }, []);
  const sheet = useRecordSheet(reload);

  useEffect(() => {
    if (!me) return;
    let active = true;
    fetchHome()
      .then((next) => { if (active) setData(next); })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "加载失败，请稍后重试"); });
    return () => { active = false; };
  }, [me]);

  const dateText = new Intl.DateTimeFormat("zh-CN", { month: "long", day: "numeric", weekday: "long" }).format(new Date());

  return (
    <div className="stack">
      <div>
        <p className="eyebrow">{me ? dateText : "\u00a0"}</p>
        <h1>{me ? `你好，${me.display_name}` : "你好"}</h1>
      </div>

      {error && <p className="error" role="alert">{error}</p>}
      {!data && !error && <section className="card"><p className="muted">正在整理今天的记录…</p></section>}
      {data && <TodayCards data={data} />}

      <button type="button" onClick={() => sheet.setTarget({ kind: null })}>＋ 记一笔</button>

      {data && (
        <section className="card">
          <div className="page-head">
            <h2>今天的记录</h2>
            <Link href="/log/">全部 ›</Link>
          </div>
          {(() => {
            const entries = entriesForDay(data.records, dayKey(new Date()));
            return entries.length === 0
              ? <p className="muted">还没有记录。吃了什么、动了多久，随手记一笔。</p>
              : <EntryList entries={entries} onSelect={(entry) => sheet.setTarget(entryTarget(entry))} />;
          })()}
        </section>
      )}

      {data && <TrendCard trends={data.trends} target={data.today.target_kcal} />}

      {sheet.target && (
        <RecordSheet
          target={sheet.target}
          onChoose={(kind) => sheet.setTarget(newTarget(kind))}
          onClose={sheet.close}
          onDone={sheet.done}
        />
      )}
    </div>
  );
}

function TodayCards({ data }: { data: HomeData }) {
  const { summary, target_kcal: target } = data.today;
  const percent = target ? Math.round((summary.kcal / target) * 100) : null;
  const weight = data.weight?.current;

  return (
    <>
      <section className="card stack">
        <div className="nutrition-head">
          <span>今日摄入</span>
          <strong>{Math.round(summary.kcal)} <small>{target ? `/ ${target} kcal` : "kcal"}</small></strong>
        </div>
        {percent !== null && (
          <div className={percent > 100 ? "progress over" : "progress"} aria-label={`已达目标的 ${percent}%`}>
            <span style={{ width: `${Math.min(percent, 100)}%` }} />
          </div>
        )}
        <p className="muted">
          {summary.meal_count} 餐 · 蛋白 {summary.protein_g} · 碳水 {summary.carbs_g} · 脂肪 {summary.fat_g} g
          {!target && <> · <Link href="/profile/">设置热量目标</Link></>}
        </p>
      </section>
      <div className="metric-grid">
        <Link className="metric" href="/exercises/">
          <span>运动</span>
          <strong>{summary.exercise_minutes} <small>分钟</small></strong>
          <small>{summary.steps ? `${summary.steps.toLocaleString("zh-CN")} 步` : "暂无步数"}</small>
        </Link>
        <Link className="metric" href="/sleeps/">
          <span>睡眠</span>
          <strong>{(summary.sleep_minutes / 60).toFixed(1)} <small>小时</small></strong>
          <small>{summary.sleep_quality ? QUALITY_LABELS[Math.round(summary.sleep_quality)] ?? "" : "暂无记录"}</small>
        </Link>
        <Link className="metric" href="/weights/">
          <span>体重</span>
          <strong>{weight ? <>{weight.weight_kg} <small>kg</small></> : "—"}</strong>
          <small>
            {!weight ? "点此记录" : data.weight?.to_target_kg != null ? `距目标 ${signedKg(data.weight.to_target_kg)} kg` : `记录于 ${weight.date}`}
          </small>
        </Link>
        <Link className="metric" href="/advice/">
          <span>规划</span>
          <strong>💡</strong>
          <small>看看明天怎么安排</small>
        </Link>
      </div>
    </>
  );
}

function TrendCard({ trends, target }: { trends: TrendDashboard; target: number | null }) {
  const max = Math.max(target ?? 0, ...trends.days.map((day) => day.kcal), 1);
  return (
    <section className="card stack">
      <h2>最近 7 天</h2>
      <div className="trend-list">
        {trends.days.map((day) => (
          <div className="trend-day" key={day.date}>
            <time dateTime={day.date}>
              {new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(new Date(`${day.date}T12:00:00`))}
            </time>
            <div className="trend-track" aria-label={`${day.kcal} 千卡`}>
              <span style={{ width: `${Math.max(day.kcal ? 4 : 0, (day.kcal / max) * 100)}%` }} />
            </div>
            <strong>{Math.round(day.kcal)}</strong>
            <small>{day.exercise_minutes} 分钟</small>
          </div>
        ))}
      </div>
      <p className="muted">绿色为每日摄入热量（kcal），右侧为运动时间。</p>
    </section>
  );
}
