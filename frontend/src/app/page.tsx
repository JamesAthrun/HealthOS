"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import type { TodayDashboard, TrendDashboard } from "@/lib/health";
import { useMe } from "@/lib/useMe";

export default function HomePage() {
  const router = useRouter();
  const me = useMe();
  const [logoutError, setLogoutError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  const [dashboard, setDashboard] = useState<TodayDashboard | null>(null);
  const [trends, setTrends] = useState<TrendDashboard | null>(null);
  const [dashboardError, setDashboardError] = useState("");

  useEffect(() => {
    if (!me) return;
    Promise.all([
      api<TodayDashboard>("/dashboard/today"),
      api<TrendDashboard>("/dashboard/trends?days=7"),
    ])
      .then(([today, sevenDays]) => {
        setDashboard(today);
        setTrends(sevenDays);
      })
      .catch((err) => {
        setDashboardError(err instanceof ApiError ? err.message : "看板加载失败，请稍后重试");
      });
  }, [me]);

  async function logout() {
    setLogoutError("");
    setLoggingOut(true);
    try {
      await api("/auth/logout", { method: "POST" });
      router.replace("/login/");
    } catch (err) {
      setLogoutError(err instanceof ApiError ? err.message : "退出失败，请检查网络后重试");
      setLoggingOut(false);
    }
  }

  if (!me) return <p>加载中…</p>;

  const maxKcal = Math.max(
    dashboard?.target_kcal ?? 0,
    ...(trends?.days.map((day) => day.kcal) ?? [1]),
    1,
  );

  return (
    <div className="stack">
      <section className="card stack">
        <div>
          <p className="eyebrow">今日概览</p>
          <h1>你好，{me.display_name}</h1>
        </div>
        {dashboardError && <p className="error" role="alert">{dashboardError}</p>}
        {!dashboard && !dashboardError && <p className="muted">正在整理今天的记录…</p>}
        {dashboard && (
          <>
            <div className="metric-grid">
              <article className="metric">
                <span>摄入</span>
                <strong>{dashboard.summary.kcal} <small>kcal</small></strong>
                <small>
                  {dashboard.target_kcal
                    ? `目标 ${dashboard.target_kcal} · ${dashboard.kcal_completion_percent}%`
                    : "尚未设置热量目标"}
                </small>
              </article>
              <article className="metric">
                <span>运动</span>
                <strong>{dashboard.summary.exercise_minutes} <small>分钟</small></strong>
                <small>{dashboard.summary.steps.toLocaleString("zh-CN")} 步</small>
              </article>
              <article className="metric">
                <span>睡眠</span>
                <strong>{(dashboard.summary.sleep_minutes / 60).toFixed(1)} <small>小时</small></strong>
                <small>{dashboard.summary.sleep_quality ? `质量 ${dashboard.summary.sleep_quality}/5` : "暂无质量评分"}</small>
              </article>
              <article className="metric">
                <span>记录</span>
                <strong>{dashboard.summary.meal_count} <small>餐</small></strong>
                <small>蛋白质 {dashboard.summary.protein_g} g</small>
              </article>
            </div>
            <div className="quick-actions" aria-label="快捷记录">
              <Link href="/meal-photo/">拍照识别</Link>
              <Link href="/meals/">记饮食</Link>
              <Link href="/exercises/">记运动</Link>
              <Link href="/sleeps/">记睡眠</Link>
            </div>
          </>
        )}
      </section>

      {trends && (
        <section className="card stack">
          <div>
            <p className="eyebrow">最近 7 天</p>
            <h2>饮食与活动趋势</h2>
          </div>
          <div className="trend-list">
            {trends.days.map((day) => (
              <div className="trend-day" key={day.date}>
                <time dateTime={day.date}>
                  {new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric" }).format(
                    new Date(`${day.date}T12:00:00`),
                  )}
                </time>
                <div className="trend-track" aria-label={`${day.kcal} 千卡`}>
                  <span style={{ width: `${Math.max(day.kcal ? 4 : 0, day.kcal / maxKcal * 100)}%` }} />
                </div>
                <strong>{day.kcal}</strong>
                <small>{day.exercise_minutes} 分钟</small>
              </div>
            ))}
          </div>
          <p className="muted">绿色表示每日摄入热量；右侧为运动时间。</p>
        </section>
      )}

      <nav className="card stack" aria-label="健康功能">
        <h2>全部功能</h2>
        <Link href="/profile/">健康档案与热量参考值</Link>
        <Link href="/records/">手工健康记录</Link>
        <Link href="/settings/">账号设置与安全记录</Link>
        <Link href="/password/">修改密码</Link>
      </nav>

      <section className="card stack">
      {logoutError && <p className="error">{logoutError}</p>}
      <button className="secondary" onClick={logout} disabled={loggingOut}>
        {loggingOut ? "退出中…" : "退出登录"}
      </button>
      </section>
    </div>
  );
}
