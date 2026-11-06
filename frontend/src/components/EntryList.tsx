"use client";

import { useCallback, useState } from "react";

import type { SheetTarget } from "@/components/RecordSheet";
import { dayLabel, type Entry, groupByDay, KIND_META, type RecordKind } from "@/lib/records";
import { useToast } from "@/lib/toast";

export function newTarget(kind: RecordKind): SheetTarget {
  return { kind, initial: null } as SheetTarget;
}

export function entryTarget(entry: Entry): SheetTarget {
  switch (entry.kind) {
    case "meal": return { kind: "meal", initial: entry.row };
    case "exercise": return { kind: "exercise", initial: entry.row };
    case "sleep": return { kind: "sleep", initial: entry.row };
    case "weight": return { kind: "weight", initial: entry.row };
  }
}

/** 页面上打开/关闭记录面板；保存后自动提示并刷新 */
export function useRecordSheet(reload: () => unknown) {
  const toast = useToast();
  const [target, setTarget] = useState<SheetTarget | null>(null);
  const close = useCallback(() => setTarget(null), []);
  const done = useCallback((message: string, tone?: "success" | "warning") => {
    setTarget(null);
    toast(message, tone);
    void reload();
  }, [reload, toast]);
  return { target, setTarget, close, done };
}

export function EntryList({ entries, onSelect, icons = true }: { entries: Entry[]; onSelect: (entry: Entry) => void; icons?: boolean }) {
  return (
    <ul className="entry-list">
      {entries.map((entry) => (
        <li key={`${entry.kind}-${entry.id}`}>
          <button type="button" className="entry" onClick={() => onSelect(entry)}>
            {icons && <span className="entry-icon" aria-hidden="true">{KIND_META[entry.kind].icon}</span>}
            <span className="entry-main">
              <strong>{entry.title}</strong>
              {entry.detail && <small>{entry.detail}</small>}
            </span>
            <span className="entry-side">{entry.side}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** 按天分组的列表（用于各类型的历史页） */
export function GroupedEntries({ entries, onSelect }: { entries: Entry[]; onSelect: (entry: Entry) => void }) {
  return (
    <>
      {groupByDay(entries, (entry) => entry.day).map((group) => (
        <section className="day-group" key={group.key}>
          <p className="day-label">{dayLabel(group.key)}</p>
          <EntryList entries={group.rows} onSelect={onSelect} icons={false} />
        </section>
      ))}
    </>
  );
}
