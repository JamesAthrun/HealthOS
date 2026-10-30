"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/useMe";

export default function PasswordPage() {
  const me = useMe();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setDone(false);
    if (next.length < 8) return setError("新密码至少 8 位");
    if (next !== confirm) return setError("两次输入的新密码不一致");
    setSubmitting(true);
    try {
      await api("/me/password", {
        method: "POST",
        body: { current_password: current, new_password: next },
      });
      setDone(true);
      setCurrent("");
      setNext("");
      setConfirm("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "网络异常，请稍后再试");
    } finally {
      setSubmitting(false);
    }
  }

  if (!me) return <p>加载中…</p>;

  return (
    <form className="card" onSubmit={onSubmit}>
      <h1>修改密码</h1>
      {error && <p className="error">{error}</p>}
      {done && <p className="success">密码已修改，其他设备需要重新登录</p>}
      <label>
        当前密码
        <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
      </label>
      <label>
        新密码（至少 8 位）
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
      </label>
      <label>
        再输入一次新密码
        <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
      </label>
      <div className="stack">
        <button type="submit" disabled={submitting}>
          {submitting ? "保存中…" : "保存"}
        </button>
        <Link href="/">返回首页</Link>
      </div>
    </form>
  );
}
