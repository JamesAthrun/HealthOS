# Infrastructure

- `Caddyfile`：入口配置。`/api/*` 转发到 FastAPI，其余请求提供前端静态文件。当前为本地开发配置（`http://localhost:8080`），Sprint 5 改为 HTTPS（`tls internal`），见 [docs/DESIGN.md](../docs/DESIGN.md) 第 7 节。

Sprint 5 会在这里加入备份脚本。
