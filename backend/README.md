# Backend

FastAPI + SQLAlchemy + Alembic。设计见 [docs/DESIGN.md](../docs/DESIGN.md)。

## 本机开发（不需要 Docker）

本地默认使用 SQLite 文件 `backend/healthos_dev.sqlite3`；部署时由 compose 改用 PostgreSQL。Compose 使用独立的迁移角色和 API 运行角色；API 角色不是表所有者且没有 `BYPASSRLS`。

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\alembic upgrade head
.\.venv\Scripts\python -m app.cli create-user alice --display-name 爱丽丝
.\.venv\Scripts\uvicorn app.main:app --reload --port 8000
```

想清空本地数据，删掉 `healthos_dev.sqlite3` 后重新执行 `alembic upgrade head`。

## 测试

默认使用临时 SQLite 文件，自动执行迁移：

```powershell
.\.venv\Scripts\pytest
```

## OpenAPI 契约

后端接口契约提交在 `backend/openapi.yml`。修改路由或 Pydantic 模型后重新生成并运行测试：

```powershell
.\.venv\Scripts\python scripts/export_openapi.py
.\.venv\Scripts\pytest
```

部署前如果想对 PostgreSQL 再跑一遍，设置 `TEST_DATABASE_URL=postgresql+psycopg://用户:密码@主机:5432/healthos_test`（会自动创建该数据库）。

写代码时只使用 SQLite 和 PostgreSQL 都支持的功能；时间字段统一用 `models.UTCDateTime`。

## 管理账号

```powershell
python -m app.cli create-user <用户名> [--display-name 名字] [--admin]
python -m app.cli reset-password <用户名>
```

在服务器上：`docker compose exec api python -m app.cli create-user <用户名>`。

## PostgreSQL 角色与 RLS

首次启动的新数据库会创建两个角色：

- `POSTGRES_MIGRATION_USER`：仅由一次性的 `migrate` 服务运行 Alembic；
- `POSTGRES_APP_USER`：API 使用的最小权限角色，受行级安全策略约束。

如果使用 Sprint 1 创建过的本地 PostgreSQL 卷，角色结构仍是旧版。开发数据不需要保留时执行 `docker compose down -v` 后重新启动；不要对生产数据这样操作。

## DeepSeek 识别试调

Sprint 3 的正式流程在前端 `/meal-photo/`：照片先在服务端验证实际格式、移除 EXIF 并压缩为 JPEG，然后才会在用户明确同意并点击识别时发送给 DeepSeek。AI 返回值始终是草稿，只有用户修改并确认后才会生成正式饮食记录并进入看板。

在仓库根目录 `.env` 配置：

```text
PHOTO_DIR=/data/photos
DEEPSEEK_API_KEY=<你的密钥>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
```

本机不设置 `PHOTO_DIR` 时使用 `backend/uploads/photos`；该目录已被 Git 忽略。Docker 使用私有 `photos_data` 卷。图片读取接口要求登录且校验所有者，不把照片目录作为静态文件公开。

当前适配器按照 DeepSeek 官方 [Vision](https://api-docs.deepseek.com/guides/vision/) 和 [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 格式传入压缩后的 JPEG。没有 API Key 或 Provider 失败时，手工饮食记录仍可正常使用。

也可用命令行脚本单独试调模型：

```powershell
.\.venv\Scripts\python scripts\probe_meal_vision.py 照片1.jpg 照片2.jpg
```
