"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";
import { useMe } from "@/lib/useMe";

export default function HomePage() {
  const router = useRouter();
  const me = useMe();

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login/");
  }

  if (!me) return <p>加载中…</p>;

  return (
    <div className="card stack">
      <h1>你好，{me.display_name}</h1>
      <p>记录功能将在下一个 Sprint 加入。</p>
      <Link href="/password/">修改密码</Link>
      <button className="secondary" onClick={logout}>
        退出登录
      </button>
    </div>
  );
}
