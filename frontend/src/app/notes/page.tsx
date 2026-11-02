"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/useMe";

type Category = "limitation" | "preference" | "tried" | "temporary";
type Note = {
  id: string;
  content: string;
  category: Category;
  expires_at: string | null;
  created_at: string;
};

const LABELS: Record<Category, string> = {
  limitation: "长期限制",
  preference: "偏好",
  tried: "尝试过",
  temporary: "临时情况",
};

export default function NotesPage() {
  const me = useMe();
  const [notes, setNotes] = useState<Note[]>([]);
  const [content, setContent] = useState("");
  const [category, setCategory] = useState<Category>("preference");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!me) return;
    api<Note[]>("/notes").then(setNotes).catch(() => setError("记录加载失败"));
  }, [me]);

  if (!me) return <p>加载中…</p>;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await api<Note>("/notes", {
        method: "POST",
        body: { content, category },
      });
      setNotes((current) => [created, ...current]);
      setContent("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    setError("");
    try {
      await api(`/notes/${id}`, { method: "DELETE" });
      setNotes((current) => current.filter((note) => note.id !== id));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "删除失败");
    }
  }

  return (
    <div className="stack">
      <form className="card stack" onSubmit={submit}>
        <div>
          <p className="eyebrow">规划上下文</p>
          <h1>关于我</h1>
          <p>记录 AI 不容易从健康数据中知道的限制、偏好和已经尝试过的方法。</p>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
        <label>
          类型
          <select value={category} onChange={(event) => setCategory(event.target.value as Category)}>
            {Object.entries(LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          内容（最多 100 字）
          <textarea required maxLength={100} value={content} onChange={(event) => setContent(event.target.value)} placeholder="例如：工作日晚上需要照顾家人" />
        </label>
        {category === "temporary" && <p className="muted">临时情况默认 7 天后自动不再用于生成规划。</p>}
        <button type="submit" disabled={busy || !content.trim()}>{busy ? "保存中…" : "添加记录"}</button>
      </form>

      <section className="card stack">
        <h2>现有记录</h2>
        {notes.length === 0 && <p className="muted">暂无记录。</p>}
        {notes.map((note) => (
          <article className="record-card" key={note.id}>
            <strong>{LABELS[note.category]}</strong>
            <p>{note.content}</p>
            {note.expires_at && <small className="muted">有效至 {new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium" }).format(new Date(note.expires_at))}</small>}
            <div className="actions"><button type="button" className="danger" onClick={() => remove(note.id)}>删除</button></div>
          </article>
        ))}
      </section>
      <Link href="/advice/">返回健康规划</Link>
      <Link href="/">返回首页</Link>
    </div>
  );
}
