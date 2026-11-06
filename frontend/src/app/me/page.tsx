"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";
import { useConfirm } from "@/lib/confirm";
import { useMe, useSetMe } from "@/lib/me";
import { useAction } from "@/lib/useAction";

export default function MePage() {
  const me = useMe();
  const setMe = useSetMe();
  const router = useRouter();
  const confirm = useConfirm();
  const { busy, error, run } = useAction();

  async function logout() {
    if (!(await confirm({ title: "退出登录？", confirmText: "退出" }))) return;
    const ok = await run(() => api("/auth/logout", { method: "POST" }), "退出失败，请检查网络后重试");
    if (ok) {
      setMe(null);
      router.replace("/login/");
    }
  }

  return (
    <div className="stack">
      <div>
        <p className="eyebrow">我的</p>
        <h1>{me?.display_name ?? "…"}</h1>
        {me && <p className="muted">账号：{me.username}</p>}
      </div>

      <section className="card">
        <h2>健康资料</h2>
        <ul className="menu-list">
          <li><Link href="/profile/">健康档案与热量参考值</Link></li>
          <li><Link href="/weights/">体重与目标</Link></li>
          <li><Link href="/notes/">关于我与食物偏好</Link></li>
        </ul>
      </section>

      <section className="card">
        <h2>账号与安全</h2>
        <ul className="menu-list">
          <li><Link href="/settings/">账号设置、AI 授权与安全记录</Link></li>
          <li><Link href="/password/">修改密码</Link></li>
        </ul>
      </section>

      {error && <p className="error" role="alert">{error}</p>}
      <button type="button" className="ghost-danger" disabled={busy} onClick={() => void logout()}>
        {busy ? "退出中…" : "退出登录"}
      </button>
      <p className="muted" style={{ textAlign: "center" }}>HealthOS 仅供健康习惯参考，不是医疗建议。</p>
    </div>
  );
}
