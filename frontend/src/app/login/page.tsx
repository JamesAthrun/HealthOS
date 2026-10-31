"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { api, ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await api("/auth/login", { method: "POST", body: { username, password } });
      router.replace("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "网络异常，请稍后再试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="card" onSubmit={onSubmit}>
      <h1>HealthOS 登录</h1>
      {error && <p className="error">{error}</p>}
      <label>
        用户名
        <input
          autoComplete="username"
          autoCapitalize="none"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
        />
      </label>
      <label>
        密码
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
      </label>
      <button type="submit" disabled={submitting}>
        {submitting ? "登录中…" : "登录"}
      </button>
    </form>
  );
}
