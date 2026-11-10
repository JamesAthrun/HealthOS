"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import { formatLocalDateTime } from "@/lib/health";
import { useMe } from "@/lib/useMe";
import { useAction } from "@/lib/useAction";

type Invite = {
  id: string;
  code_hint: string;
  note: string | null;
  status: "active" | "used" | "expired" | "revoked";
  created_at: string;
  expires_at: string;
  used_at: string | null;
  used_by_username: string | null;
};

const STATUS_LABELS: Record<Invite["status"], string> = {
  active: "可用",
  used: "已使用",
  expired: "已过期",
  revoked: "已作废",
};

export default function InvitesPage() {
  const me = useMe();
  const confirm = useConfirm();
  const { busy, error, setError, run } = useAction();
  const [invites, setInvites] = useState<Invite[] | null>(null);
  const [note, setNote] = useState("");
  const [created, setCreated] = useState<{ code: string; link: string } | null>(null);

  const reload = useCallback(async () => {
    try {
      setInvites(await api<Invite[]>("/admin/invites"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  }, [setError]);

  useEffect(() => {
    if (!me?.is_admin) return;
    let active = true;
    api<Invite[]>("/admin/invites")
      .then((data) => { if (active) setInvites(data); })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "加载失败"); });
    return () => { active = false; };
  }, [me, setError]);

  async function onCreate(e: FormEvent) {
    e.preventDefault();
    await run(async () => {
      const invite = await api<Invite & { code: string }>("/admin/invites", {
        method: "POST",
        body: { note: note.trim() || null },
      });
      setCreated({ code: invite.code, link: `${window.location.origin}/register/?code=${invite.code}` });
      setNote("");
      await reload();
    }, "生成失败，请稍后重试");
  }

  async function revoke(invite: Invite) {
    const ok = await confirm({
      title: `作废邀请码 …${invite.code_hint}？`,
      message: "作废后这个邀请码不能再用来注册。",
      confirmText: "作废",
      danger: true,
    });
    if (!ok) return;
    if (await run(() => api(`/admin/invites/${invite.id}`, { method: "DELETE" }), "作废失败")) await reload();
  }

  if (!me) return <p className="muted">加载中…</p>;
  if (!me.is_admin) return <p className="muted">只有管理员可以管理邀请码。</p>;

  return (
    <div className="stack">
      <h1>邀请码</h1>
      <form className="card stack" onSubmit={onCreate}>
        <p className="muted">每个邀请码只能注册一个账号，7 天内有效。生成后把邀请码或注册链接发给家人。</p>
        <label>
          备注（可选，例如给谁）
          <input maxLength={50} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <button type="submit" disabled={busy}>{busy ? "处理中…" : "生成邀请码"}</button>
        {created && (
          <div className="stack">
            <p className="invite-code">{created.code}</p>
            <p className="muted">注册链接（长按复制）：</p>
            <p className="invite-link">{created.link}</p>
            <p className="muted">邀请码只在这里显示一次，离开页面后无法再查看；忘了可以作废后重新生成。</p>
          </div>
        )}
      </form>

      <section className="card">
        <h2>最近的邀请码</h2>
        {error && <p className="error" role="alert">{error}</p>}
        {!invites && !error && <p className="muted">加载中…</p>}
        {invites && invites.length === 0 && <p className="muted">还没有生成过邀请码。</p>}
        {invites && invites.length > 0 && (
          <ul className="entry-list">
            {invites.map((invite) => (
              <li key={invite.id}>
                <div className="entry">
                  <span className="entry-main">
                    <strong>…{invite.code_hint}{invite.note ? ` · ${invite.note}` : ""}</strong>
                    <small>
                      {invite.status === "used"
                        ? `${invite.used_by_username ?? "已删除的账号"} 于 ${formatLocalDateTime(invite.used_at!)} 注册`
                        : `${formatLocalDateTime(invite.expires_at)} 到期`}
                    </small>
                  </span>
                  <span className="entry-side">
                    {STATUS_LABELS[invite.status]}
                    {invite.status === "active" && (
                      <>
                        <br />
                        <button type="button" className="link-button" disabled={busy} onClick={() => void revoke(invite)}>作废</button>
                      </>
                    )}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
