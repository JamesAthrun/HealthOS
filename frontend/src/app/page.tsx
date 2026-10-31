"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { api, ApiError } from "@/lib/api";
import { useMe } from "@/lib/useMe";

export default function HomePage() {
  const router = useRouter();
  const me = useMe();
  const [logoutError, setLogoutError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);

  async function logout() {
    setLogoutError("");
    setLoggingOut(true);
    try {
      await api("/auth/logout", { method: "POST" });
      router.replace("/login/");
    } catch (err) {
      setLogoutError(err instanceof ApiError ? err.message : "退出失败，请检查网络后重试");
      setLoggingOut(false);
    }
  }

  if (!me) return <p>加载中…</p>;

  return (
    <div className="card stack">
      <h1>你好，{me.display_name}</h1>
      <p>记录功能将在下一个 Sprint 加入。</p>
      {logoutError && <p className="error">{logoutError}</p>}
      <Link href="/password/">修改密码</Link>
      <button className="secondary" onClick={logout} disabled={loggingOut}>
        {loggingOut ? "退出中…" : "退出登录"}
      </button>
    </div>
  );
}
