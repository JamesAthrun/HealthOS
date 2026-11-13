import type { MetadataRoute } from "next";

// 静态导出时生成 /manifest.webmanifest；“添加到主屏幕”后像 App 一样全屏打开
export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "HealthOS 家庭健康记录",
    short_name: "HealthOS",
    description: "记录饮食、运动、睡眠和体重，AI 帮你估算营养",
    lang: "zh-CN",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f6f7f9",
    theme_color: "#2f855a",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icons/maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
