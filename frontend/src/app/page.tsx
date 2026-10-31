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
      <p>第二阶段进行中：档案已开放，手工记录页面正在逐步加入。</p>
      {logoutError && <p className="error">{logoutError}</p>}
      <Link href="/profile/">健康档案与热量参考值</Link>
      <Link href="/records/">手工健康记录</Link>
      <Link href="/settings/">账号设置与安全记录</Link>
      <Link href="/password/">修改密码</Link>
      <button className="secondary" onClick={logout} disabled={loggingOut}>
        {loggingOut ? "退出中…" : "退出登录"}
      </button>
    </div>
  );
}
