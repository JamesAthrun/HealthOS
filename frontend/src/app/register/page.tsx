"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";

import { api, ApiError, type Me } from "@/lib/api";
import { useSetMe } from "@/lib/me";

function RegisterForm() {
  const router = useRouter();
  const setMe = useSetMe();
  const params = useSearchParams();
  // 管理员可以直接分享 /register/?code=XXXX-XXXX
  const [code, setCode] = useState(() => params.get("code") ?? "");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!/^[a-z0-9_]{3,32}$/.test(username.trim().toLowerCase())) {
      return setError("用户名只能用小写字母、数字和下划线，3–32 位");
    }
    if (password.length < 8) return setError("密码至少 8 位");
    if (password !== confirm) return setError("两次输入的密码不一致");
    setSubmitting(true);
    try {
      const me = await api<Me>("/auth/register", {
        method: "POST",
        body: { invite_code: code, username, password, display_name: displayName.trim() || null },
      });
      setMe(me);
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "网络异常，请稍后再试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card" onSubmit={onSubmit}>
      <h1>注册 HealthOS</h1>
      <p className="muted">需要家人给你的邀请码，一个邀请码只能注册一个账号。</p>
      {error && <p className="error" role="alert">{error}</p>}
      <label>
        邀请码
        <input autoCapitalize="characters" autoComplete="off" placeholder="XXXX-XXXX" value={code} onChange={(e) => setCode(e.target.value)} required />
      </label>
      <label>
        用户名（登录用，小写字母/数字/下划线）
        <input autoComplete="username" autoCapitalize="none" maxLength={32} value={username} onChange={(e) => setUsername(e.target.value)} required />
      </label>
      <label>
        显示名称（可选）
        <input maxLength={50} placeholder="例如：妈妈" value={displayName} onChange={(e) => setDisplayName(e.target.value)} />
      </label>
      <label>
        密码（至少 8 位）
        <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      </label>
      <label>
        再输入一次密码
        <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
      </label>
      <button type="submit" disabled={submitting}>
        {submitting ? "注册中…" : "注册并登录"}
      </button>
      <p className="muted" style={{ textAlign: "center" }}>
        已有账号？<Link href="/login/">去登录</Link>
      </p>
    </form>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={<p className="muted">加载中…</p>}>
      <RegisterForm />
    </Suspense>
  );
}
