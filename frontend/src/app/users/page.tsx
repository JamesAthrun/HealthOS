"use client";

import { useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import { formatLocalDateTime } from "@/lib/health";
import { useToast } from "@/lib/toast";
import { useAction } from "@/lib/useAction";
import { useMe } from "@/lib/useMe";

type AdminUser = {
  id: string;
  username: string;
  display_name: string;
  is_admin: boolean;
  created_at: string;
  last_login_at: string | null;
  locked: boolean;
};

export default function UsersPage() {
  const me = useMe();
  const confirm = useConfirm();
  const toast = useToast();
  const { busy, error, setError, run } = useAction();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [reset, setReset] = useState<{ username: string; password: string } | null>(null);
  const [deleting, setDeleting] = useState<AdminUser | null>(null);
  const [confirmName, setConfirmName] = useState("");

  const reload = useCallback(async () => {
    try {
      setUsers(await api<AdminUser[]>("/admin/users"));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  }, [setError]);

  useEffect(() => {
    if (!me?.is_admin) return;
    let active = true;
    api<AdminUser[]>("/admin/users")
      .then((data) => { if (active) setUsers(data); })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "加载失败"); });
    return () => { active = false; };
  }, [me, setError]);

  async function resetPassword(user: AdminUser) {
    const ok = await confirm({
      title: `重置 ${user.display_name}（${user.username}）的密码？`,
      message: "会生成一个临时密码，对方所有设备需要重新登录。请把临时密码告诉对方，并提醒登录后到“我的 → 修改密码”改掉。",
      confirmText: "重置",
    });
    if (!ok) return;
    await run(async () => {
      const result = await api<{ temporary_password: string }>(`/admin/users/${user.id}/reset-password`, { method: "POST" });
      setReset({ username: user.username, password: result.temporary_password });
      await reload();
    }, "重置失败");
  }

  async function deleteUser() {
    if (!deleting) return;
    const target = deleting;
    const ok = await run(async () => {
      await api(`/admin/users/${target.id}/delete`, { method: "POST", body: { confirm_username: confirmName } });
    }, "删除失败");
    if (!ok) return;
    setDeleting(null);
    setConfirmName("");
    toast(`已删除 ${target.username}`);
    await reload();
  }

  if (!me) return <p className="muted">加载中…</p>;
  if (!me.is_admin) return <p className="muted">只有管理员可以管理用户。</p>;

  return (
    <div className="stack">
      <h1>用户管理</h1>
      {error && <p className="error" role="alert">{error}</p>}

      {reset && (
        <section className="card stack">
          <h2>{reset.username} 的临时密码</h2>
          <p className="invite-code">{reset.password}</p>
          <p className="muted">只显示这一次。请告诉对方用它登录，再到“我的 → 修改密码”改成自己的密码。</p>
          <button type="button" className="secondary" onClick={() => setReset(null)}>我已记下</button>
        </section>
      )}

      {deleting && (
        <section className="card stack">
          <h2>删除 {deleting.display_name}（{deleting.username}）？</h2>
          <p className="error">会永久删除这个账号的所有数据：饮食、运动、睡眠、体重、照片、建议等，无法恢复。</p>
          <label>
            请输入用户名 <strong>{deleting.username}</strong> 确认
            <input autoCapitalize="none" autoComplete="off" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} />
          </label>
          <button
            type="button"
            className="ghost-danger"
            disabled={busy || confirmName.trim().toLowerCase() !== deleting.username}
            onClick={() => void deleteUser()}
          >
            {busy ? "删除中…" : "永久删除"}
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => { setDeleting(null); setConfirmName(""); }}>取消</button>
        </section>
      )}

      <section className="card">
        {!users && !error && <p className="muted">加载中…</p>}
        {users && (
          <ul className="entry-list">
            {users.map((user) => (
              <li key={user.id}>
                <div className="entry">
                  <span className="entry-main">
                    <strong>
                      {user.display_name}（{user.username}）
                      {user.is_admin ? " · 管理员" : ""}
                      {user.locked ? " · 已锁定" : ""}
                    </strong>
                    <small>
                      注册于 {formatLocalDateTime(user.created_at)}
                      {" · "}
                      {user.last_login_at ? `最近登录 ${formatLocalDateTime(user.last_login_at)}` : "暂无登录中的设备"}
                    </small>
                  </span>
                  {user.id !== me.id && (
                    <span className="entry-side stack" style={{ gap: 4 }}>
                      <button type="button" className="link-button" disabled={busy} onClick={() => void resetPassword(user)}>重置密码</button>
                      <button type="button" className="link-button text-danger" disabled={busy} onClick={() => { setDeleting(user); setConfirmName(""); setReset(null); }}>删除</button>
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <p className="muted">“最近登录”只统计还没过期、没退出的登录。</p>
    </div>
  );
}
