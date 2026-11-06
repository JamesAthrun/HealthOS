import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AppShell } from "@/components/AppShell";

export const metadata: Metadata = {
  title: "HealthOS",
  description: "家庭健康记录",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // 让 env(safe-area-inset-*) 在 iPhone 刘海/底部横条区域生效
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
