"use client";

import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/useMe";
import { useConfirm } from "@/lib/confirm";
import { FoodPrefButtons, useFoodPreferences } from "@/lib/foodPrefs";

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
  const confirm = useConfirm();
  const [notes, setNotes] = useState<Note[]>([]);
  const [content, setContent] = useState("");
  const [category, setCategory] = useState<Category>("preference");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const foodPrefs = useFoodPreferences(Boolean(me));
  const [frequent, setFrequent] = useState<{ food_name: string; count: number }[]>([]);

  useEffect(() => {
    if (!me) return;
    api<Note[]>("/notes").then(setNotes).catch(() => setError("记录加载失败"));
    api<{ food_name: string; count: number }[]>("/food-preferences/frequent").then(setFrequent).catch(() => setFrequent([]));
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
    if (!(await confirm({ title: "删除这条记录？", message: "删除后 AI 规划将不再参考它。", confirmText: "删除", danger: true }))) return;
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
      <section className="card stack">
        <div>
          <h2>食物偏好</h2>
          <p className="muted">在饮食记录、拍照识别和参考餐单里点“喜欢 / 不想再吃”即可添加。生成明日建议时，餐单会优先使用喜欢和常吃的食物。</p>
        </div>
        {foodPrefs.error && <p className="error" role="alert">{foodPrefs.error}</p>}
        {foodPrefs.prefs.length === 0 && <p className="muted">还没有标记。</p>}
        {foodPrefs.prefs.map((pref) => (
          <div className="pref-row" key={pref.id}>
            <span>{pref.food_name} · {pref.sentiment === "like" ? "喜欢" : "不想再吃"}</span>
            <span className="pref-buttons"><button type="button" onClick={() => void foodPrefs.remove(pref.id)}>删除</button></span>
          </div>
        ))}
        {frequent.length > 0 && (
          <>
            <h3>最近 30 天常吃</h3>
            {frequent.map((food) => (
              <div className="pref-row" key={food.food_name}>
                <span>{food.food_name} · {food.count} 次</span>
                <FoodPrefButtons name={food.food_name} current={foodPrefs.find(food.food_name)?.sentiment} onToggle={foodPrefs.toggle} />
              </div>
            ))}
          </>
        )}
      </section>
      <Link href="/advice/">返回健康规划</Link>
    </div>
  );
}
