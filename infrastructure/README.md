# Infrastructure

- `Caddyfile`：入口配置。`/api/*` 转发到 FastAPI，其余请求提供前端静态文件。当前为本地开发配置（`http://localhost:8080`），Sprint 5 改为 HTTPS（`tls internal`），见 [docs/DESIGN.md](../docs/DESIGN.md) 第 7 节。


## 部署

在本机（Windows，已配置好阿里云 `workbench` CLI）运行：

```powershell
powershell -ExecutionPolicy Bypass -File infrastructure/deploy.ps1
```

它会检查工作区已提交且不落后远端、构建前端、打包当前提交和 `frontend/out`、上传，并在服务器后台运行 `deploy-remote.sh`：

1. 先备份数据库和当前网页到 `/root/backups/*-before-deploy-<时间>.*`（保留最近 10 份）
2. 解压源码、重建 api 镜像、`docker compose up -d`（migrate 服务自动执行数据库迁移），重启 caddy
3. 替换网页文件，但保留旧的 `_next/static`（手机缓存的旧页面仍能加载样式，30 天后清理）
4. 安装每日备份脚本和 cron
5. 健康检查，输出回滚用的备份文件名

## 备份

- `backup.sh` 安装为 `/usr/local/bin/healthos-backup`，每天 03:30 运行（`/etc/cron.d/healthos-backup`）。
- 备份到 `/root/backups/daily/`：数据库 `healthos-*.dump`（会用 `pg_restore --list` 校验）和照片 `photos-*.tar.gz`，保留 14 天，日志在 `backup.log`。
- 这些备份和数据在同一台服务器上，建议定期下载一份到别处。恢复方法见 `backup.sh` 开头的注释。
