# Frontend

Next.js（App Router），生产构建为纯静态文件（`out/`），由 Caddy 提供。

```bash
npm install
npm run dev     # http://localhost:3000，/api 转发到 http://127.0.0.1:8000
npm run build   # 生成 out/
```

限制：静态导出不支持服务端功能（SSR、Server Actions、rewrites 等），页面都用客户端组件，通过 `/api` 调用后端。
