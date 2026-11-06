"use client";

import { RecordTypePage } from "@/components/RecordTypePage";
import { api } from "@/lib/api";
import type { Meal } from "@/lib/health";
import { mealEntry } from "@/lib/records";

const load = async () => (await api<Meal[]>("/meals")).map(mealEntry);

export default function MealsPage() {
  return (
    <RecordTypePage
      title="饮食"
      kind="meal"
      load={load}
      emptyText="还没有饮食记录。点右下角“＋ 记饮食”，可以拍照、打字或说一句话。"
    />
  );
}
