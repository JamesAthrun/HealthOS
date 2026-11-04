import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ConfirmProvider } from "@/lib/confirm";
import { TopBar } from "@/lib/TopBar";

export const metadata: Metadata = {
  title: "HealthOS",
  description: "家庭健康记录",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN">
      <body>
        <ConfirmProvider>
          <TopBar />
          <main className="container">{children}</main>
        </ConfirmProvider>
      </body>
    </html>
  );
}
