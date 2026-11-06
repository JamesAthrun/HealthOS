"use client";

import { type ReactNode, useCallback, useEffect, useState } from "react";

import { GroupedEntries, entryTarget, newTarget, useRecordSheet } from "@/components/EntryList";
import { RecordSheet } from "@/components/RecordSheet";
import { ApiError } from "@/lib/api";
import type { Entry, RecordKind } from "@/lib/records";
import { useMe } from "@/lib/useMe";

/** 饮食/运动/睡眠/体重历史页的统一结构：标题 + 添加按钮 + 按天分组的列表，点一条即可编辑 */
export function RecordTypePage({
  title,
  kind,
  load,
  emptyText,
  headExtra,
  top,
}: {
  title: string;
  kind: RecordKind;
  load: () => Promise<Entry[]>;
  emptyText: string;
  headExtra?: ReactNode;
  /** 列表上方的内容；version 在每次保存后递增，便于一起刷新 */
  top?: (version: number) => ReactNode;
}) {
  const me = useMe();
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);

  const reload = useCallback(async () => {
    try {
      setEntries(await load());
      setVersion((v) => v + 1);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "加载失败");
    }
  }, [load]);
  const sheet = useRecordSheet(reload);

  useEffect(() => {
    if (!me) return;
    let active = true;
    load()
      .then((data) => { if (active) setEntries(data); })
      .catch((err) => { if (active) setError(err instanceof ApiError ? err.message : "加载失败"); });
    return () => { active = false; };
  }, [me, load]);

  return (
    <div className="stack">
      <div className="page-head">
        <h1>{title}</h1>
        <div style={{ display: "flex", gap: 8 }}>
          {headExtra}
          <button type="button" onClick={() => sheet.setTarget(newTarget(kind))}>＋ 添加</button>
        </div>
      </div>
      {top?.(version)}
      <section className="card">
        {error && <p className="error" role="alert">{error}</p>}
        {!entries && !error && <p className="muted">加载中…</p>}
        {entries && entries.length === 0 && <p className="muted">{emptyText}</p>}
        {entries && <GroupedEntries entries={entries} onSelect={(entry) => sheet.setTarget(entryTarget(entry))} />}
      </section>
      {sheet.target && (
        <RecordSheet
          target={sheet.target}
          onChoose={(next) => sheet.setTarget(newTarget(next))}
          onClose={sheet.close}
          onDone={sheet.done}
        />
      )}
    </div>
  );
}
