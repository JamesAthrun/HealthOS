"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import { type Friend, notifyMessagesChanged } from "@/lib/friends";
import { useToast } from "@/lib/toast";
import { useAction } from "@/lib/useAction";

export default function FriendsPage() {
  const confirm = useConfirm();
  const toast = useToast();
  const { busy, error, run } = useAction();
  const [friends, setFriends] = useState<Friend[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [username, setUsername] = useState("");

  const reload = useCallback(async () => {
    try {
      setFriends(await api<Friend[]>("/friends"));
      setLoadError("");
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "加载失败");
    }
  }, []);

  useEffect(() => {
    let active = true;
    api<Friend[]>("/friends")
      .then((next) => { if (active) setFriends(next); })
      .catch((err) => { if (active) setLoadError(err instanceof ApiError ? err.message : "加载失败"); });
    return () => { active = false; };
  }, []);

  async function add(e: FormEvent) {
    e.preventDefault();
    let status = "";
    const ok = await run(async () => {
      ({ status } = await api<{ status: string }>("/friends/requests", { method: "POST", body: { username: username.trim() } }));
    }, "发送失败，请稍后重试");
    if (!ok) return;
    setUsername("");
    if (status === "accepted") {
      toast("对方也加过你，已成为好友");
      notifyMessagesChanged();
      await reload();
    } else {
      toast("已发送好友请求，等对方在“消息”里确认");
    }
  }

  async function remove(friend: Friend) {
    if (!(await confirm({
      title: `删除好友 ${friend.user.display_name}？`,
      message: "双方还没处理的共餐邀请会一起取消；已经记下的饮食记录不受影响。",
      confirmText: "删除",
      danger: true,
    }))) return;
    if (await run(() => api(`/friends/${friend.user.id}`, { method: "DELETE" }), "删除失败")) {
      toast("已删除好友");
      notifyMessagesChanged();
      await reload();
    }
  }

  return (
    <div className="stack">
      <div>
        <p className="eyebrow">我的</p>
        <h1>好友</h1>
        <p className="muted">加为好友后，可以把一起吃的饭分享给对方，对方确认后记到自己的账户里。好友看不到你的其他记录。</p>
      </div>

      <form className="card stack" onSubmit={add}>
        <h2>添加好友</h2>
        {error && <p className="error" role="alert">{error}</p>}
        <label>对方的用户名
          <input value={username} maxLength={32} autoCapitalize="none" autoCorrect="off" onChange={(e) => setUsername(e.target.value)} required />
          <small>在对方的“我的”页面顶部可以看到。</small>
        </label>
        <button type="submit" disabled={busy || !username.trim()}>{busy ? "发送中…" : "发送好友请求"}</button>
      </form>

      <section className="card">
        <h2>我的好友</h2>
        {loadError && <p className="error" role="alert">{loadError}</p>}
        {friends === null && !loadError && <p className="muted">加载中…</p>}
        {friends?.length === 0 && <p className="muted">还没有好友。</p>}
        {friends?.map((friend) => (
          <div key={friend.user.id} className="record-card friend-row">
            <div>
              <strong>{friend.user.display_name}</strong>
              <p className="muted">@{friend.user.username}</p>
            </div>
            <button type="button" className="text-danger" disabled={busy} onClick={() => void remove(friend)}>删除</button>
          </div>
        ))}
      </section>
    </div>
  );
}
