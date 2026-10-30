# HealthOS

**AI Personal Health Copilot — 面向个人与家庭的健康记录与规划工具。**

HealthOS 帮助用户记录饮食、运动和睡眠，并基于本人确认的数据生成可执行的每日建议与每周计划。产品定位是生活方式管理，不提供疾病诊断、治疗方案或紧急医疗服务。

> 开发原则：Production-minded architecture, MVP-sized features.
>
> 架构按照未来商业产品的标准设计，功能按照个人与家庭 MVP 的范围逐步实现。

## MVP 范围

- 独立账号与健康档案
- 饮食拍照识别、编辑与确认
- 运动和睡眠记录
- 今日概览与 7 天趋势
- 次日建议与每周计划
- 数据导出、记录删除与账号删除

家庭成员可以分别注册，但默认互不可见。任何未来的家庭共享都必须由数据所有者主动授权。

## 文档导航

| 文档 | 读者 | 内容 |
| --- | --- | --- |
| [产品介绍](docs/PRODUCT_OVERVIEW.md) | 家人、早期用户 | HealthOS 做什么、不做什么、如何保护隐私 |
| [MVP PRD](docs/MVP_PRD.md) | 产品、设计、开发 | 用户故事、范围、流程和验收标准 |
| [系统设计](docs/SYSTEM_DESIGN.md) | 开发、运维 | 架构、模块边界、部署与关键决策 |
| [数据库设计](docs/DATABASE_DESIGN.md) | 后端、数据 | 数据所有权、核心表、约束和 RLS |
| [API 设计](docs/API_DESIGN.md) | 前后端 | REST 约定、端点和错误模型 |
| [AI 架构](docs/AI_ARCHITECTURE.md) | AI、后端、产品 | 识别与规划流程、隐私、评估和降级 |
| [安全与隐私](docs/SECURITY_PRIVACY.md) | 全团队 | 威胁模型、安全基线、备份与响应 |
| [开发路线](docs/ROADMAP.md) | 项目负责人 | 阶段、任务、验收门槛和发布条件 |
| [Sprint 与上线计划](docs/SPRINT_ROLLOUT_PLAN.md) | 项目负责人、开发、运维 | 逐 Sprint 交付、本地测试和 Docker 服务器部署 |

## 推荐技术栈

- Frontend: Next.js + React + TypeScript，响应式 Web / PWA
- Backend: FastAPI + SQLAlchemy + Alembic，模块化单体
- Database: PostgreSQL
- Object storage: S3-compatible private bucket
- Authentication: OIDC / OAuth 2.0 Authorization Code + PKCE
- AI: provider-neutral adapter with structured outputs
- Local deployment: Docker Compose

## 仓库结构

```text
healthos/
├── docs/                  # 产品和工程设计
├── frontend/              # Next.js 应用（阶段 0 创建）
├── backend/               # FastAPI 应用（阶段 0 创建）
├── infrastructure/        # 部署、备份和可观测性配置
├── tests/                 # 跨模块与安全验收测试
├── .env.example
└── docker-compose.yml
```

## 当前状态

本仓库当前是 **设计基线 v0.1**：已明确 MVP、系统边界、安全基线、数据模型和 API 草案，但尚未开始业务代码实现。任何真实健康数据都不应放入 Git、Issue、普通日志或开发种子数据中。

## 快速开始（基础设施占位）

1. 复制 `.env.example` 为 `.env`，仅填写本地开发值。
2. 执行 `docker compose up -d postgres minio`。
3. 根据 [开发路线](docs/ROADMAP.md) 完成阶段 0 工程初始化。

`.env`、密钥、上传文件、数据库目录和备份均被排除在版本控制之外。

## 决策原则

1. 用户确认的数据优先于 AI 推断。
2. 数据所有权属于用户；家庭关系不等于访问授权。
3. 应用层授权是第一道防线，数据库 RLS 是第二道防线。
4. AI 只接收完成任务所必需的最少数据。
5. 先做可维护的单体；只有出现可衡量的扩展需求时才拆服务。

## 许可与使用

当前为私有项目，尚未选择开源许可。未经项目所有者明确同意，不得公开仓库或使用真实家庭健康数据进行演示。
