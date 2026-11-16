"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ShareAcceptForm } from "@/components/ShareAcceptForm";
import { Sheet } from "@/components/Sheet";
import { api, ApiError } from "@/lib/api";
import { type Message, type Messages, notifyMessagesChanged, ratioLabel, scaleItems } from "@/lib/friends";
import { formatLocalDateTime } from "@/lib/health";
import { mealTotals } from "@/lib/nutrition";
import { MEAL_LABELS } from "@/lib/records";
import { useToast } from "@/lib/toast";
import { useAction } from "@/lib/useAction";

const STATUS_LABELS: Record<Message["status"], string> = {
  pending: "等待确认",
  accepted: "已接受",
  declined: "已拒绝",
  cancelled: "已取消",
  expired: "已过期",
};

function needsAction(m: Message): boolean {
  if (m.direction !== "in") return false;
  return m.status === "pending" || Boolean(m.share?.update_pending && m.status === "accepted");
}

function mealSummary(m: Message): string {
  const share = m.share!;
  const names = share.food_items.map((f) => f.name).join("、");
  return `${MEAL_LABELS[share.meal_type]} · ${formatLocalDateTime(share.eaten_at)} · ${names}`;
}

function describe(m: Message): string {
  const name = m.other.display_name;
  if (m.kind === "friend_request") {
    if (m.direction === "in") return m.status === "accepted" ? `你和 ${name} 成为了好友` : `${name} 想加你为好友`;
    return m.status === "accepted" ? `${name} 接受了你的好友请求` : `你向 ${name} 发出了好友请求`;
  }
  if (m.direction === "in") {
    if (m.share?.update_pending) return `${name} 修改了你们一起吃的这餐`;
    return `${name} 邀请你记录一起吃的这餐`;
  }
  return `你邀请 ${name} 记录这餐（${ratioLabel(m.share!.ratio)}）`;
}

export default function MessagesPage() {
  const toast = useToast();
  const { busy, error, run } = useAction();
  const [data, setData] = useState<Messages | null>(null);
  const [loadError, setLoadError] = useState("");
  const [accepting, setAccepting] = useState<Message | null>(null);

  const reload = useCallback(async () => {
    try {
      setData(await api<Messages>("/messages"));
      setLoadError("");
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : "加载失败");
    }
    notifyMessagesChanged();
  }, []);

  useEffect(() => {
    let active = true;
    api<Messages>("/messages")
      .then((next) => { if (active) setData(next); })
      .catch((err) => { if (active) setLoadError(err instanceof ApiError ? err.message : "加载失败"); });
    return () => { active = false; };
  }, []);

  async function act(path: string, done: string, body?: unknown) {
    if (await run(() => api(path, { method: "POST", body }), "操作失败，请稍后重试")) {
      toast(done);
      await reload();
    }
  }

  const todo = data?.items.filter(needsAction) ?? [];
  const rest = data?.items.filter((m) => !needsAction(m)) ?? [];

  function card(m: Message) {
    const share = m.share;
    const kcal = share ? Math.round(mealTotals(scaleItems(share.food_items, share.ratio)).kcal) : 0;
    const pending = m.status === "pending";
    return (
      <div key={m.id} className="record-card stack">
        <div>
          <strong>{describe(m)}</strong>
          <p className="muted">
            {formatLocalDateTime(m.created_at)}
            {!needsAction(m) && ` · ${STATUS_LABELS[m.status]}`}
          </p>
        </div>
        {share && (
          <>
            {pending && share.photo_count > 0 && (
              <div className="photo-strip">
                {Array.from({ length: share.photo_count }, (_, i) => (
                  <div key={i} className="photo-thumb" style={{ backgroundImage: `url(/api/meal-shares/${m.id}/photos/${i}?size=thumb)` }}>
                    <a href={`/api/meal-shares/${m.id}/photos/${i}`} target="_blank" rel="noreferrer" aria-label={`查看第 ${i + 1} 张照片`} />
                  </div>
                ))}
              </div>
            )}
            <p>{mealSummary(m)}</p>
            <p className="muted">
              整餐 {Math.round(mealTotals(share.food_items).kcal)} kcal
              {m.direction === "in" && ` · 建议你的份额 ${ratioLabel(share.ratio)} ≈ ${kcal} kcal`}
            </p>
          </>
        )}
        {m.direction === "in" && pending && m.kind === "friend_request" && (
          <div className="actions">
            <button type="button" disabled={busy} onClick={() => void act(`/friends/requests/${m.id}/accept`, "已成为好友")}>接受</button>
            <button type="button" className="secondary" disabled={busy} onClick={() => void act(`/friends/requests/${m.id}/decline`, "已拒绝")}>拒绝</button>
          </div>
        )}
        {m.direction === "in" && pending && m.kind === "meal_share" && (
          <div className="actions">
            <button type="button" disabled={busy} onClick={() => setAccepting(m)}>接受…</button>
            <button type="button" className="secondary" disabled={busy} onClick={() => void act(`/meal-shares/${m.id}/decline`, "已拒绝")}>拒绝</button>
          </div>
        )}
        {m.direction === "in" && m.status === "accepted" && share?.update_pending && (
          <>
            <p className="muted">同步后，你的这条记录会按你的份额（{ratioLabel(share.ratio)}）更新菜品、餐次和时间。</p>
            <div className="actions">
              <button type="button" disabled={busy} onClick={() => void act(`/meal-shares/${m.id}/sync`, "已同步", { apply: true })}>同步更新</button>
              <button type="button" className="secondary" disabled={busy} onClick={() => void act(`/meal-shares/${m.id}/sync`, "已忽略", { apply: false })}>忽略</button>
            </div>
          </>
        )}
        {m.direction === "out" && pending && m.kind === "meal_share" && (
          <button type="button" className="text-danger" disabled={busy} onClick={() => void act(`/meal-shares/${m.id}/cancel`, "已撤回")}>撤回邀请</button>
        )}
      </div>
    );
  }

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <p className="eyebrow">我的</p>
          <h1>消息</h1>
        </div>
        <Link className="button secondary" href="/friends/">好友</Link>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {loadError && <p className="error" role="alert">{loadError}</p>}
      {!data && !loadError && <p className="muted">加载中…</p>}

      {data && (
        <section className="card">
          <h2>待处理</h2>
          {todo.length === 0 ? <p className="muted">没有需要处理的消息。</p> : todo.map(card)}
        </section>
      )}
      {rest.length > 0 && (
        <section className="card">
          <h2>历史</h2>
          {rest.map(card)}
        </section>
      )}
      {data?.items.length === 0 && (
        <p className="muted">在饮食记录里点“与好友共享”，就能把一起吃的饭发给好友。先去 <Link href="/friends/">添加好友</Link>。</p>
      )}

      {accepting && (
        <Sheet title={`${accepting.other.display_name} 的共餐邀请`} onClose={() => setAccepting(null)}>
          <ShareAcceptForm
            message={accepting}
            onDone={(text) => {
              setAccepting(null);
              toast(text);
              void reload();
            }}
          />
        </Sheet>
      )}
    </div>
  );
}
