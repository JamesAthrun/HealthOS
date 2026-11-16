"use client";

import { useCallback, useEffect, useState } from "react";

import { InvitesPanel } from "@/components/admin/InvitesPanel";
import { UsersPanel } from "@/components/admin/AdminUsersPanel";
import { api, ApiError } from "@/lib/api";
import { formatLocalDateTime } from "@/lib/health";
import { useMe } from "@/lib/useMe";

type UserUsage = {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
  locked: boolean;
  last_login_at: string | null;
  meals_today: number;
  meals_7d: number;
  ai_today: number;
  ai_7d: number;
  advice_7d: number;
};

type Dashboard = {
  generated_at: string;
  users: UserUsage[];
  ai: {
    daily_limit: number;
    calls_today: number;
    calls_7d: number;
    failed_7d: number;
    avg_ms_7d: number | null;
    slowest_ms_7d: number | null;
    by_kind_7d: Record<string, number>;
    failures_7d: { outcome: string; count: number }[];
    advice_7d: number;
    advice_failed_7d: number;
  };
  server: {
    disk_total_bytes: number;
    disk_free_bytes: number;
    photos_bytes: number;
    db_bytes: number | null;
    last_backup: { finished_at: string; ok: boolean; db_bytes: number | null; photos_bytes: number | null; message: string | null } | null;
    last_ok_backup_at: string | null;
  };
  security_events: { created_at: string; username: string; event_type: string; outcome: string; ip_address: string | null }[];
};

const KIND_LABELS: Record<string, string> = {
  photo: "单张照片",
  photos: "拍照识别",
  preview: "重新识别",
  text: "文字识别",
  estimate: "营养估算",
};

const OUTCOME_LABELS: Record<string, string> = {
  AI_TIMEOUT: "超时",
  AI_INVALID_RESPONSE: "返回格式不对",
  AI_NOT_CONFIGURED: "未配置",
  error: "其他错误",
  pending: "未结束",
};

const EVENT_LABELS: Record<string, string> = {
  login: "登录失败",
  registered: "注册了新账号",
  password_changed: "修改了密码",
  admin_password_reset: "管理员重置了密码",
  admin_user_deleted: "管理员删除了账号",
  invite_created: "生成了邀请码",
};

function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function formatSeconds(ms: number | null): string {
  return ms === null ? "—" : `${(ms / 1000).toFixed(1)} 秒`;
}

function hoursSince(iso: string, now: string): number {
  return (new Date(now).getTime() - new Date(iso).getTime()) / 3_600_000;
}

export default function AdminPage() {
  const me = useMe();
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    try {
      setData(await api<Dashboard>("/admin/dashboard"));
      setError("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    if (!me?.is_admin) return;
    let active = true;
    api<Dashboard>("/admin/dashboard")
      .then((next) => { if (active) setData(next); })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "加载失败"); });
    return () => { active = false; };
  }, [me]);

  if (!me) return <p className="muted">加载中…</p>;
  if (!me.is_admin) return <p className="muted">只有管理员可以查看管理后台。</p>;

  const backup = data?.server.last_backup;
  const backupStale = data && (!data.server.last_ok_backup_at || hoursSince(data.server.last_ok_backup_at, data.generated_at) > 36);
  const diskUsedRatio = data ? 1 - data.server.disk_free_bytes / data.server.disk_total_bytes : 0;

  return (
    <div className="stack">
      <div className="page-head">
        <h1>管理后台</h1>
        <button type="button" className="secondary" onClick={() => void reload()}>刷新</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {!data && !error && <p className="muted">加载中…</p>}

      {data && (
        <>
          <section className="card stack">
            <h2>概览</h2>
            <div className="stat-grid">
              <div><small>账号</small><strong>{data.users.length}</strong></div>
              <div><small>今天记录的饮食</small><strong>{data.users.reduce((n, u) => n + u.meals_today, 0)}</strong></div>
              <div><small>今天 AI 调用</small><strong>{data.ai.calls_today}</strong></div>
              <div><small>近 7 天 AI 失败</small><strong className={data.ai.failed_7d ? "text-warning" : ""}>{data.ai.failed_7d}</strong></div>
            </div>
            {backupStale && <p className="error">超过 36 小时没有成功的备份，请检查服务器上的每日备份。</p>}
            {diskUsedRatio > 0.85 && <p className="error">磁盘已用 {Math.round(diskUsedRatio * 100)}%，请清理空间。</p>}
          </section>

          <section className="card stack">
            <h2>家庭成员使用情况</h2>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>成员</th><th>饮食 今天/7天</th><th>AI 今天/7天</th><th>建议 7天</th><th>最近登录</th></tr>
                </thead>
                <tbody>
                  {data.users.map((u) => (
                    <tr key={u.id}>
                      <td>
                        {u.display_name}
                        <small>{u.username}{u.is_admin ? " · 管理员" : ""}{u.locked ? " · 已锁定" : ""}</small>
                      </td>
                      <td>{u.meals_today} / {u.meals_7d}</td>
                      <td className={!u.is_admin && u.ai_today >= data.ai.daily_limit * 0.8 ? "text-warning" : ""}>{u.ai_today} / {u.ai_7d}</td>
                      <td>{u.advice_7d}</td>
                      <td>{u.last_login_at ? formatLocalDateTime(u.last_login_at) : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted">AI 每人每天上限 {data.ai.daily_limit} 次（管理员不限）。只统计数量，不显示记录内容。</p>
          </section>

          <section className="card stack">
            <h2>AI 调用（近 7 天）</h2>
            <div className="stat-grid">
              <div><small>识别/估算</small><strong>{data.ai.calls_7d}</strong></div>
              <div><small>平均耗时</small><strong>{formatSeconds(data.ai.avg_ms_7d)}</strong></div>
              <div><small>最慢一次</small><strong>{formatSeconds(data.ai.slowest_ms_7d)}</strong></div>
              <div><small>规划建议</small><strong>{data.ai.advice_7d}{data.ai.advice_failed_7d ? `（失败 ${data.ai.advice_failed_7d}）` : ""}</strong></div>
            </div>
            {Object.keys(data.ai.by_kind_7d).length > 0 && (
              <p className="muted">
                {Object.entries(data.ai.by_kind_7d).map(([kind, count]) => `${KIND_LABELS[kind] ?? kind} ${count}`).join(" · ")}
              </p>
            )}
            {data.ai.failures_7d.length > 0 ? (
              <p className="muted">
                失败：{data.ai.failures_7d.map((f) => `${OUTCOME_LABELS[f.outcome] ?? f.outcome} ${f.count} 次`).join("，")}
              </p>
            ) : (
              <p className="muted">近 7 天没有失败。</p>
            )}
          </section>

          <section className="card stack">
            <h2>服务器</h2>
            <div className="stat-grid">
              <div><small>磁盘剩余</small><strong>{formatBytes(data.server.disk_free_bytes)}</strong><small>共 {formatBytes(data.server.disk_total_bytes)}</small></div>
              <div><small>照片占用</small><strong>{formatBytes(data.server.photos_bytes)}</strong></div>
              <div><small>数据库</small><strong>{formatBytes(data.server.db_bytes)}</strong></div>
              <div>
                <small>最近备份</small>
                <strong className={backup && !backup.ok ? "text-warning" : ""}>{backup ? (backup.ok ? "成功" : "失败") : "暂无"}</strong>
                {backup && <small>{formatLocalDateTime(backup.finished_at)}</small>}
              </div>
            </div>
            {backup?.ok && <p className="muted">数据库 {formatBytes(backup.db_bytes)}，照片 {formatBytes(backup.photos_bytes)}；每天 03:30 自动备份，保留 14 天。</p>}
            {backup && !backup.ok && <p className="error">{backup.message ?? "备份失败"}</p>}
          </section>

          <section className="card stack">
            <h2>最近的安全事件（14 天）</h2>
            {data.security_events.length === 0 ? (
              <p className="muted">没有需要注意的事件。</p>
            ) : (
              <ul className="entry-list">
                {data.security_events.map((e, i) => (
                  <li key={`${e.created_at}-${i}`}>
                    <div className="entry">
                      <span className="entry-main">
                        <strong className={e.event_type === "login" ? "text-warning" : ""}>{e.username} · {EVENT_LABELS[e.event_type] ?? e.event_type}</strong>
                        <small>{formatLocalDateTime(e.created_at)}{e.ip_address ? ` · ${e.ip_address}` : ""}</small>
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <p className="muted">连续输错 5 次密码会锁定 15 分钟；被锁定的账号会在上面的成员列表里标出。</p>
          </section>
        </>
      )}

      <UsersPanel meId={me.id} onChanged={() => void reload()} />
      <InvitesPanel />
    </div>
  );
}
