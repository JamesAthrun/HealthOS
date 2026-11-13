import { defineConfig, devices } from "@playwright/test";

// 端到端测试：自动启动临时后端（backend/scripts/e2e_server.py，端口 8100）和前端开发服务器（端口 3100）。
// 本地运行：npm run e2e（默认用本机已装的 Edge/Chrome；CI 里用 Playwright 自带的 Chromium）
const python = process.env.E2E_PYTHON ?? (process.platform === "win32" ? "../backend/.venv/Scripts/python.exe" : "python");
const channel = process.env.CI ? undefined : (process.env.E2E_BROWSER_CHANNEL ?? (process.platform === "win32" ? "msedge" : undefined));

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:3100",
    ...devices["iPhone 13"],
    // iPhone 预设默认用 WebKit；这里统一用 Chromium 内核模拟手机尺寸
    defaultBrowserType: "chromium",
    channel,
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `"${python}" ../backend/scripts/e2e_server.py`,
      url: "http://127.0.0.1:8100/api/health",
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: "npx next dev --port 3100",
      url: "http://localhost:3100/login/",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { HEALTHOS_API_URL: "http://127.0.0.1:8100" },
    },
  ],
});
