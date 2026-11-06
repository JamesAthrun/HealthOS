"use client";

import { RecordTypePage } from "@/components/RecordTypePage";
import { api } from "@/lib/api";
import type { Sleep } from "@/lib/health";
import { sleepEntry } from "@/lib/records";

const load = async () => (await api<Sleep[]>("/sleeps")).map(sleepEntry);

export default function SleepsPage() {
  return <RecordTypePage title="睡眠" kind="sleep" load={load} emptyText="还没有睡眠记录" />;
}
