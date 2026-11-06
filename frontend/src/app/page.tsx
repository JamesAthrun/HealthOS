"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EntryList, entryTarget, newTarget, useRecordSheet } from "@/components/EntryList";
import { Fab } from "@/components/Fab";
import { RecordSheet } from "@/components/RecordSheet";
import { TodayNutrition, useDailyTargets } from "@/components/TodayNutrition";
import { api, ApiError } from "@/lib/api";
import { dayIntake } from "@/lib/dailyNutrition";
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
  const [version, setVersion] = useState(0);
  const targets = useDailyTargets(version);

  const reload = useCallback(async () => {
    try {
      setData(await fetchHome());
      setVersion((v) => v + 1);
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
      {data && <MiniStats data={data} />}
      {data && (
        <TodayNutrition
          intake={dayIntake(data.records.meals.filter((meal) => dayKey(meal.eaten_at) === dayKey(new Date())))}
          targets={targets}
        />
      )}

      {data && (
        <section className="card">
          <div className="page-head">
            <h2>今天的记录</h2>
            <Link href="/log/">全部 ›</Link>
          </div>
          {(() => {
            const entries = entriesForDay(data.records, dayKey(new Date()));
            return entries.length === 0
              ? <p className="muted">还没有记录。点右下角“＋”，吃了什么、动了多久随手记一笔。</p>
              : <EntryList entries={entries} onSelect={(entry) => sheet.setTarget(entryTarget(entry))} />;
          })()}
        </section>
      )}

      {data && <WeekChart trends={data.trends} target={targets.kcal} />}

      <Fab onClick={() => sheet.setTarget({ kind: null })} />

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

/** 运动、睡眠、体重：一行三个小卡片，点进去看详情 */
function MiniStats({ data }: { data: HomeData }) {
  const { summary } = data.today;
  const weight = data.weight?.current;
  return (
    <div className="mini-stats">
      <Link href="/exercises/">
        <span aria-hidden="true">🏃</span>
        <strong>{summary.exercise_minutes}<small> 分钟</small></strong>
        <small>{summary.steps ? `${summary.steps.toLocaleString("zh-CN")} 步` : "运动"}</small>
      </Link>
      <Link href="/sleeps/">
        <span aria-hidden="true">😴</span>
        <strong>{summary.sleep_minutes ? (summary.sleep_minutes / 60).toFixed(1) : "—"}<small> 小时</small></strong>
        <small>{summary.sleep_quality ? `睡得${QUALITY_LABELS[Math.round(summary.sleep_quality)] ?? ""}` : "睡眠"}</small>
      </Link>
      <Link href="/weights/">
        <span aria-hidden="true">⚖️</span>
        <strong>{weight ? weight.weight_kg : "—"}<small> kg</small></strong>
        <small>{data.weight?.to_target_kg != null ? `距目标 ${signedKg(data.weight.to_target_kg)}` : "体重"}</small>
      </Link>
    </div>
  );
}

/** 最近 7 天摄入热量的柱状图；虚线是每日参考热量 */
function WeekChart({ trends, target }: { trends: TrendDashboard; target: number }) {
  const max = Math.max(target * 1.2, ...trends.days.map((day) => day.kcal), 1);
  const today = dayKey(new Date());
  return (
    <section className="card stack">
      <div className="page-head">
        <h2>最近 7 天</h2>
        <small className="muted">摄入 kcal</small>
      </div>
      <div className="week-chart" role="img" aria-label="最近 7 天每日摄入热量">
        <div className="week-target" style={{ bottom: `${(target / max) * 100}%` }} />
        {trends.days.map((day) => (
          <div className="week-bar" key={day.date}>
            <span className={day.kcal > target ? "over" : undefined} style={{ height: `${(day.kcal / max) * 100}%` }}>
              {day.kcal > 0 && <small>{Math.round(day.kcal)}</small>}
            </span>
          </div>
        ))}
      </div>
      <div className="week-labels">
        {trends.days.map((day) => (
          <time key={day.date} dateTime={day.date} className={day.date === today ? "today" : undefined}>
            {day.date === today ? "今天" : new Intl.DateTimeFormat("zh-CN", { weekday: "narrow" }).format(new Date(`${day.date}T12:00:00`))}
          </time>
        ))}
      </div>
      <p className="muted">虚线为每日参考 {target} kcal，超过显示为橙色。</p>
    </section>
  );
}
