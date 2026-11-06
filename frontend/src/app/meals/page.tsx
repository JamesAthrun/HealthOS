"use client";

import Link from "next/link";

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
      emptyText="还没有饮食记录。可以拍照识别，也可以手动添加。"
      headExtra={<Link className="button secondary" href="/meal-photo/">📷 拍照</Link>}
    />
  );
}
