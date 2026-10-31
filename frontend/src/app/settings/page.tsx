"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError, type AuditEvent, type Me } from "@/lib/api";
import { useMe } from "@/lib/useMe";

const EVENT_LABELS: Record<string, string> = {
  login: "登录",
  logout: "退出登录",
  password_changed: "修改密码",
  settings_changed: "修改账号设置",
  session_expired: "会话过期",
  ai_consent_granted: "同意 AI 图片处理",
  ai_consent_revoked: "撤回 AI 图片处理同意",
  meal_ai_confirmed: "确认 AI 饮食草稿",
};

type Consent = { granted: boolean; granted_at: string | null };

export default function SettingsPage() {
  const me = useMe();

  if (!me) return <p>加载中…</p>;
  return <SettingsContent key={me.id} initialMe={me} />;
}

function SettingsContent({ initialMe }: { initialMe: Me }) {
  const [displayName, setDisplayName] = useState(initialMe.display_name);
  const [timezone, setTimezone] = useState(initialMe.timezone);
  const [locale, setLocale] = useState(initialMe.locale);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [consent, setConsent] = useState<Consent | null>(null);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    Promise.all([api<AuditEvent[]>("/me/audit-events"), api<Consent>("/ai-consent")])
      .then(([auditEvents, aiConsent]) => {
        setEvents(auditEvents);
        setConsent(aiConsent);
      })
      .catch(() => setEvents([]));
  }, []);

  async function revokeConsent() {
    setError("");
    try {
      setConsent(await api<Consent>("/ai-consent", { method: "DELETE" }));
      setEvents(await api<AuditEvent[]>("/me/audit-events"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "撤回失败，请稍后重试");
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setDone(false);
    setSubmitting(true);
    try {
      await api<Me>("/me/settings", {
        method: "PUT",
        body: { display_name: displayName, timezone, locale },
      });
      setDone(true);
      setEvents(await api<AuditEvent[]>("/me/audit-events"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "网络异常，请稍后再试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="stack">
      <form className="card" onSubmit={onSubmit}>
        <h1>账号设置</h1>
        {error && <p className="error" role="alert">{error}</p>}
        {done && <p className="success" role="status">设置已保存</p>}
        <label>
          显示名称
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={50} required />
        </label>
        <label>
          时区
          <select value={timezone} onChange={(e) => setTimezone(e.target.value)}>
            <option value="Asia/Shanghai">中国标准时间（上海）</option>
            <option value="Asia/Hong_Kong">香港时间</option>
            <option value="Asia/Tokyo">日本时间（东京）</option>
            <option value="Europe/London">英国时间（伦敦）</option>
            <option value="America/Los_Angeles">美国太平洋时间</option>
          </select>
        </label>
        <label>
          界面语言
          <select value={locale} onChange={(e) => setLocale(e.target.value)}>
            <option value="zh-CN">简体中文</option>
            <option value="en-US">English (US)</option>
            <option value="en-GB">English (UK)</option>
          </select>
        </label>
        <button type="submit" disabled={submitting}>
          {submitting ? "保存中…" : "保存设置"}
        </button>
      </form>

      <section className="card stack">
        <h1>AI 图片处理</h1>
        {consent?.granted ? (
          <>
            <p>已同意在你主动点击识别时，将餐食照片发送给 DeepSeek。撤回后不会再发起新的 AI 识别。</p>
            <button type="button" className="secondary" onClick={revokeConsent}>撤回 AI 图片处理同意</button>
          </>
        ) : (
          <p>当前未同意 AI 图片处理。手工饮食记录不受影响。</p>
        )}
      </section>

      <section className="card">
        <h1>最近安全活动</h1>
        {events.length === 0 ? (
          <p>暂无记录</p>
        ) : (
          <ul className="event-list">
            {events.slice(0, 10).map((event) => (
              <li key={event.id}>
                {EVENT_LABELS[event.event_type] ?? event.event_type}
                {event.outcome === "denied" ? "（已拒绝）" : ""}
                <small>
                  {new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
                    new Date(event.created_at),
                  )}
                  {event.ip_address ? ` · ${event.ip_address}` : ""}
                </small>
              </li>
            ))}
          </ul>
        )}
      </section>

      <Link href="/">返回首页</Link>
    </div>
  );
}
