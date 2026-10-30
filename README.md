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
frontend/        Next.js（阶段 1 创建）
backend/         FastAPI（阶段 1 创建）
infrastructure/  Caddy 配置、备份脚本
tests/           跨用户隔离等测试
```

## 本地启动（目前只有数据库）

1. 复制 `.env.example` 为 `.env`，填写本地使用的值。
2. 运行 `docker compose up -d postgres`。

不要把 `.env`、真实健康数据或照片提交到 Git。
