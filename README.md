# HealthOS

家庭版健康记录小工具：记录饮食（拍照识别）、运动和睡眠，查看 7 天趋势，并用 AI 生成明日建议和每周计划。

仅供家人使用，不提供医疗诊断。

## 文档

- [设计（家庭版）](docs/DESIGN.md) — 范围、架构、数据模型、API、AI、部署、备份、开发计划
- [产品介绍](docs/PRODUCT_OVERVIEW.md) — 给家人看的说明
- [archive/](docs/archive/) — 早期面向商业产品的详细设计，目前不执行，仅供参考

## 技术栈

Next.js（静态导出）+ FastAPI + PostgreSQL + DeepSeek，用 Docker Compose 部署在一台 2 核 2 GB 的云服务器上，通过 IP 加 HTTPS 访问。

## 仓库结构

```text
docs/            设计文档
frontend/        Next.js，构建为静态文件
backend/         FastAPI、Alembic 迁移、测试
infrastructure/  Caddy 配置
```

## 本地开发（不需要 Docker）

本地使用 SQLite 文件（`backend/healthos_dev.sqlite3`），不需要安装数据库。前端需要 Node.js 20.9 或更高版本（推荐 Node.js 22）。先复制 `.env.example` 为 `.env`。

```powershell
# 后端（首次运行的步骤见 backend/README.md），运行在 :8000
cd backend; .\.venv\Scripts\uvicorn app.main:app --reload --port 8000

# 前端，另开一个终端
cd frontend; npm install; npm run dev
```

打开 http://localhost:3000。

## 部署（Docker）

只有部署时使用 Docker Compose 和 PostgreSQL，步骤见 [docs/DESIGN.md](docs/DESIGN.md) 第 7 节。部署前也可以在本机用同一套容器验证：

```powershell
docker compose up -d --build
docker compose run --rm api alembic upgrade head
docker compose exec api python -m app.cli create-user alice
```

前端会在 Docker 的 Node.js 构建阶段生成静态文件，服务器不需要另外安装 Node.js。

打开 http://localhost:8080。

不要把 `.env`、真实健康数据或照片提交到 Git。
