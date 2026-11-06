"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EntryList, entryTarget, newTarget, useRecordSheet } from "@/components/EntryList";
import { RecordSheet } from "@/components/RecordSheet";
import { ApiError } from "@/lib/api";
import {
  type AllRecords,
  dayKey,
  dayLabel,
  entriesForDay,
  fetchAllRecords,
  formatMinutes,
  mealKcal,
  shiftDay,
  sleepMinutes,
} from "@/lib/records";
import { useMe } from "@/lib/useMe";

export default function LogPage() {
  const me = useMe();
  const today = dayKey(new Date());
  const [day, setDay] = useState(today);
  const [all, setAll] = useState<AllRecords | null>(null);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    try {
      setAll(await fetchAllRecords());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "记录加载失败");
    }
  }, []);
  const sheet = useRecordSheet(reload);

  useEffect(() => {
    if (!me) return;
    let active = true;
    fetchAllRecords()
      .then((data) => { if (active) setAll(data); })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "记录加载失败"); });
    return () => { active = false; };
  }, [me]);

  const entries = all ? entriesForDay(all, day) : [];
  const kcal = entries.reduce((sum, e) => sum + (e.kind === "meal" ? mealKcal(e.row) : 0), 0);
  const exercise = entries.reduce((sum, e) => sum + (e.kind === "exercise" ? e.row.minutes : 0), 0);
  const sleep = entries.reduce((sum, e) => sum + (e.kind === "sleep" ? sleepMinutes(e.row) : 0), 0);

  return (
    <div className="stack">
      <div className="page-head">
        <h1>记录</h1>
        <button type="button" onClick={() => sheet.setTarget({ kind: null })}>＋ 记一笔</button>
      </div>

      <section className="card stack">
        <div className="day-nav">
          <button type="button" className="icon-button" aria-label="前一天" onClick={() => setDay(shiftDay(day, -1))}>‹</button>
          <div style={{ textAlign: "center" }}>
            <strong>{dayLabel(day)}</strong>
            {day !== today && (
              <div><button type="button" className="link-button" onClick={() => setDay(today)}>回到今天</button></div>
            )}
          </div>
          <button type="button" className="icon-button" aria-label="后一天" disabled={day >= today} onClick={() => setDay(shiftDay(day, 1))}>›</button>
        </div>
        {entries.length > 0 && (
          <p className="muted" style={{ textAlign: "center" }}>
            摄入 {kcal} kcal · 运动 {exercise} 分钟{sleep > 0 && ` · 睡眠 ${formatMinutes(sleep)}`}
          </p>
        )}
        {error && <p className="error" role="alert">{error}</p>}
        {!all && !error && <p className="muted">加载中…</p>}
        {all && entries.length === 0 && (
          <p className="muted" style={{ textAlign: "center" }}>这一天还没有记录，点右上角“＋ 记一笔”添加。</p>
        )}
        <EntryList entries={entries} onSelect={(entry) => sheet.setTarget(entryTarget(entry))} />
      </section>

      <section className="card">
        <h2>按类型查看</h2>
        <ul className="menu-list">
          <li><Link href="/meals/">🍚 饮食记录</Link></li>
          <li><Link href="/exercises/">🏃 运动记录</Link></li>
          <li><Link href="/sleeps/">😴 睡眠记录</Link></li>
          <li><Link href="/weights/">⚖️ 体重与趋势</Link></li>
        </ul>
      </section>

      {sheet.target && (
        <RecordSheet
          target={sheet.target}
          day={day}
          onChoose={(kind) => sheet.setTarget(newTarget(kind))}
          onClose={sheet.close}
          onDone={sheet.done}
        />
      )}
    </div>
  );
}
