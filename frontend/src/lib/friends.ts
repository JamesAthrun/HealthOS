"use client";

import { useEffect, useState } from "react";

import { api } from "./api";
import type { FoodItemInput, Meal } from "./health";
import { type DraftItem, NUTRIENTS } from "./nutrition";

export type UserBrief = { id: string; username: string; display_name: string };

export type Friend = { user: UserBrief; since: string | null };

export type ShareInfo = {
  eaten_at: string;
  meal_type: Meal["meal_type"];
  food_items: FoodItemInput[];
  photo_count: number;
  ratio: number;
  created_meal_id: string | null;
  update_pending: boolean;
};

export type Message = {
  id: string;
  kind: "friend_request" | "meal_share";
  direction: "in" | "out";
  status: "pending" | "accepted" | "declined" | "cancelled" | "expired";
  other: UserBrief;
  created_at: string;
  responded_at: string | null;
  share: ShareInfo | null;
};

export type Messages = { unread: number; items: Message[] };

/** 消息有变化（处理了请求、发出了邀请）时通知角标刷新 */
const CHANGED = "healthos:messages-changed";

export function notifyMessagesChanged() {
  window.dispatchEvent(new Event(CHANGED));
}

/** 未读消息数：打开时、回到页面时、每分钟和消息变化时刷新 */
export function useUnreadMessages(enabled = true): number {
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const refresh = () => {
      api<{ unread: number }>("/messages/unread-count")
        .then((r) => { if (active) setUnread(r.unread); })
        .catch(() => undefined);
    };
    refresh();
    const timer = window.setInterval(refresh, 60_000);
    const onVisible = () => { if (document.visibilityState === "visible") refresh(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener(CHANGED, refresh);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener(CHANGED, refresh);
    };
  }, [enabled]);
  return enabled ? unread : 0;
}

/** 整餐按比例分成自己那一份（营养按精确比例算，份量只保留两位小数） */
export function scaleItems(items: FoodItemInput[], ratio: number): DraftItem[] {
  const part = (value: number | null | undefined) => (typeof value === "number" ? Math.round(value * ratio * 10) / 10 : value);
  return items.map((item) => {
    const scaled: DraftItem = { ...item, quantity: Math.max(Math.round(item.quantity * ratio * 100) / 100, 0.01), kcal: part(item.kcal) as number };
    for (const { key } of NUTRIENTS) scaled[key] = part(item[key]) as never;
    return scaled;
  });
}

export function ratioLabel(ratio: number): string {
  if (ratio >= 0.999) return "全部";
  const n = Math.round(1 / ratio);
  if (Math.abs(1 / n - ratio) < 0.01) return `1/${n}`;
  return `${Math.round(ratio * 100)}%`;
}
