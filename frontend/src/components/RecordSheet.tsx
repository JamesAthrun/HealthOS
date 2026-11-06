"use client";

import { Sheet } from "@/components/Sheet";
import { ExerciseForm } from "@/components/forms/ExerciseForm";
import { MealCapture } from "@/components/forms/MealCapture";
import { MealForm } from "@/components/forms/MealForm";
import { SleepForm } from "@/components/forms/SleepForm";
import { WeightForm } from "@/components/forms/WeightForm";
import type { Exercise, Meal, Sleep, WeightLog } from "@/lib/health";
import { KIND_META, type RecordKind } from "@/lib/records";

export type SheetTarget =
  | { kind: null }
  | { kind: "meal"; initial: Meal | null }
  | { kind: "exercise"; initial: Exercise | null }
  | { kind: "sleep"; initial: Sleep | null }
  | { kind: "weight"; initial: WeightLog | null };

/** 添加/编辑记录的底部面板。kind 为空时先让用户选择记什么。 */
export function RecordSheet({
  target,
  day,
  onChoose,
  onClose,
  onDone,
}: {
  target: SheetTarget;
  day?: string;
  onChoose: (kind: RecordKind) => void;
  onClose: () => void;
  onDone: (message: string, tone?: "success" | "warning") => void;
}) {
  const label = target.kind ? KIND_META[target.kind].label : "";
  const title = !target.kind ? "记一笔" : target.initial ? `编辑${label}` : `记${label}`;

  return (
    <Sheet title={title} onClose={onClose}>
      {target.kind === null && (
        <div className="add-grid">
          {(Object.keys(KIND_META) as RecordKind[]).map((kind) => (
            <button key={kind} type="button" onClick={() => onChoose(kind)}>
              <span>{KIND_META[kind].icon}</span>
              {KIND_META[kind].label}
            </button>
          ))}
        </div>
      )}
      {target.kind === "meal" && (target.initial
        ? <MealForm initial={target.initial} day={day} onDone={onDone} />
        : <MealCapture day={day} onDone={onDone} />)}
      {target.kind === "exercise" && <ExerciseForm initial={target.initial} day={day} onDone={onDone} />}
      {target.kind === "sleep" && <SleepForm initial={target.initial} day={day} onDone={onDone} />}
      {target.kind === "weight" && <WeightForm initial={target.initial} day={day} onDone={onDone} />}
    </Sheet>
  );
}
