"use client";

import { RecordTypePage } from "@/components/RecordTypePage";
import { api } from "@/lib/api";
import type { Exercise } from "@/lib/health";
import { exerciseEntry } from "@/lib/records";

const load = async () => (await api<Exercise[]>("/exercises")).map(exerciseEntry);

export default function ExercisesPage() {
  return <RecordTypePage title="运动" kind="exercise" load={load} emptyText="还没有运动记录" />;
}
