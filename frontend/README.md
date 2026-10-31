# Frontend

Next.js（App Router），生产构建为纯静态文件（`out/`），由 Caddy 提供。

需要 Node.js 20.9 或更高版本，推荐使用仓库 `.nvmrc` 指定的 Node.js 22。

```bash
npm install
npm run dev     # http://localhost:3000，/api 转发到 http://127.0.0.1:8000
npm run build   # 生成 out/
```

如果后端不在默认的 `127.0.0.1:8000`，启动前设置 `HEALTHOS_API_URL`，例如 `HEALTHOS_API_URL=http://127.0.0.1:8001 npm run dev`。

限制：静态导出不支持服务端功能（SSR、Server Actions、rewrites 等），页面都用客户端组件，通过 `/api` 调用后端。
