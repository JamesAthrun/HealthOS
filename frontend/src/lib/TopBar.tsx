"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** 子页面顶部统一的返回首页入口；首页和登录页不显示 */
export function TopBar() {
  const pathname = usePathname();
  if (pathname === "/" || pathname.startsWith("/login")) return null;
  return (
    <header className="topbar">
      <Link href="/">‹ 首页</Link>
    </header>
  );
}
