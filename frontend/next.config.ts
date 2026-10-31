import type { NextConfig } from "next";
import { PHASE_DEVELOPMENT_SERVER } from "next/constants";

// 生产构建为纯静态文件（out/），由 Caddy 提供，服务器上不运行 Node.js。
// 本地 `npm run dev` 时不能使用静态导出，改为把 /api 转发到本机 FastAPI。
export default function config(phase: string): NextConfig {
  if (phase === PHASE_DEVELOPMENT_SERVER) {
    const apiBaseUrl = (process.env.HEALTHOS_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
    return {
      async rewrites() {
        return [{ source: "/api/:path*", destination: `${apiBaseUrl}/api/:path*` }];
      },
    };
  }
  return {
    output: "export",
    trailingSlash: true,
  };
}
