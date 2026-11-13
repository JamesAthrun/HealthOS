"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";

import { ConfirmProvider } from "@/lib/confirm";
import { MeProvider } from "@/lib/me";
import { ToastProvider } from "@/lib/toast";

const TABS = [
  { href: "/", label: "今天", icon: "🏠", match: (p: string) => p === "/" },
  { href: "/log/", label: "记录", icon: "📋", match: (p: string) => /^\/(log|meals|exercises|sleeps|weights)(\/|$)/.test(p) },
  { href: "/advice/", label: "规划", icon: "💡", match: (p: string) => /^\/(advice|notes)(\/|$)/.test(p) },
  { href: "/me/", label: "我的", icon: "👤", match: (p: string) => /^\/(me|profile|targets|settings|password|invites|users)(\/|$)/.test(p) },
];

// 二级页面返回时的默认去处（直接打开链接、没有浏览历史时使用）
const PARENTS: [RegExp, string][] = [
  [/^\/(meals|exercises|sleeps|weights)(\/|$)/, "/log/"],
  [/^\/notes(\/|$)/, "/advice/"],
  [/^\/(profile|targets|settings|password|invites|users)(\/|$)/, "/me/"],
];

function normalize(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/$/, "") : pathname;
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = normalize(usePathname());
  const router = useRouter();
  const onLogin = pathname.startsWith("/login") || pathname.startsWith("/register");
  const isTab = ["/", "/log", "/advice", "/me"].includes(pathname);
  const parent = PARENTS.find(([pattern]) => pattern.test(pathname))?.[1] ?? "/";

  function back() {
    if (window.history.length > 1) router.back();
    else router.push(parent);
  }

  return (
    <MeProvider>
      <ToastProvider>
        <ConfirmProvider>
          {!onLogin && !isTab && (
            <header className="topbar">
              <button type="button" className="link-button" onClick={back}>‹ 返回</button>
            </header>
          )}
          <main className={onLogin ? "container" : "container with-tabbar"}>{children}</main>
          {!onLogin && (
            <nav className="tabbar" aria-label="主导航">
              {TABS.map((tab) => (
                <Link key={tab.href} href={tab.href} aria-current={tab.match(pathname) ? "page" : undefined}>
                  <span aria-hidden="true">{tab.icon}</span>
                  {tab.label}
                </Link>
              ))}
            </nav>
          )}
        </ConfirmProvider>
      </ToastProvider>
    </MeProvider>
  );
}
