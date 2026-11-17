"use client";

import Link from "next/link";
import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { type Friend, notifyMessagesChanged, ratioLabel } from "@/lib/friends";
import type { Meal } from "@/lib/health";
import { useAction } from "@/lib/useAction";

/** 编辑饮食时“与好友共享”：选好友和份额，对方在消息页确认后记到自己的账户 */
export function MealSharePanel({ meal, onDone }: { meal: Meal; onDone: (message: string) => void }) {
  const { busy, error, run } = useAction();
  const [friends, setFriends] = useState<Friend[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [scaleMine, setScaleMine] = useState(true);
  // 一起吃但没有用 HealthOS 的人，也要算进平分人数
  const [others, setOthers] = useState(0);
  const people = selected.length + 1 + others;
  const ratio = 1 / people;

  function load(open: boolean) {
    if (!open || friends) return;
    api<Friend[]>("/friends")
      .then(setFriends)
      .catch((err) => setLoadError(err instanceof ApiError ? err.message : "加载好友失败"));
  }

  function toggle(id: string) {
    setSelected((current) => (current.includes(id) ? current.filter((x) => x !== id) : [...current, id]));
  }

  async function share() {
    let shared = 0;
    const ok = await run(async () => {
      ({ shared } = await api<{ shared: number }>(`/meals/${meal.id}/shares`, {
        method: "POST",
        body: { friend_ids: selected, ratio, my_ratio: scaleMine ? ratio : null },
      }));
    }, "分享失败，请稍后重试");
    if (!ok) return;
    notifyMessagesChanged();
    onDone(shared ? `已发给 ${shared} 位好友，等对方确认` : "已经分享过给这些好友了");
  }

  return (
    <details className="more" onToggle={(e) => load(e.currentTarget.open)}>
      <summary>🤝 和好友分享这一餐</summary>
      <div className="stack">
        {(error || loadError) && <p className="error" role="alert">{error || loadError}</p>}
        {friends === null && !loadError && <p className="muted">加载中…</p>}
        {friends?.length === 0 && <p className="muted">还没有好友，先去 <Link href="/friends/">添加好友</Link>。</p>}
        {friends && friends.length > 0 && (
          <>
            <p className="muted">按已保存的内容分享（不含备注）。对方确认后会记到他自己的账户，可以自己调整份量。</p>
            <div>
              <span className="field-label">和谁一起吃的</span>
              <div className="chips" role="group" aria-label="好友">
                {friends.map((f) => (
                  <button key={f.user.id} type="button" aria-pressed={selected.includes(f.user.id)} onClick={() => toggle(f.user.id)}>
                    {f.user.display_name}
                  </button>
                ))}
              </div>
            </div>
            {selected.length > 0 && (
              <>
                <div>
                  <span className="field-label">一共几个人吃</span>
                  <div className="chips stepper" role="group" aria-label="一共几个人吃">
                    <button type="button" aria-label="减少一人" disabled={others === 0} onClick={() => setOthers((n) => Math.max(0, n - 1))}>−</button>
                    <strong>{people} 人</strong>
                    <button type="button" aria-label="增加一人" disabled={people >= 20} onClick={() => setOthers((n) => n + 1)}>+</button>
                  </div>
                  <small className="muted">
                    你 + {selected.length} 位好友{others > 0 ? ` + ${others} 位没用 HealthOS 的人` : ""}，平分后每人约 {ratioLabel(ratio)}。有人没用这个系统就点 +。
                  </small>
                </div>
                <label className="checkbox-label">
                  <input type="checkbox" checked={scaleMine} onChange={(e) => setScaleMine(e.target.checked)} />
                  我记的是整餐，把我的记录也改成 {ratioLabel(ratio)}
                </label>
                <button type="button" disabled={busy} onClick={() => void share()}>
                  {busy ? "发送中…" : `发送共餐邀请`}
                </button>
              </>
            )}
          </>
        )}
      </div>
    </details>
  );
}
