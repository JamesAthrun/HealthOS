# HealthOS 数据库设计 v0.1

## 1. 核心原则

- `user_id` 表示数据所有者；`household_id` 只表示关系，两者不能互换。
- 健康数据表必须有不可为空的所有者列和所有者范围索引。
- 客户端不能指定或修改所有者。
- AI 推断、用户确认值和生成来源分别保存。
- 所有时间为 `timestamptz`；本地日期按用户 IANA 时区计算。
- 枚举在早期可使用带 CHECK 的文本，避免数据库枚举难以演进。

## 2. 实体关系概览

```text
users 1---1 health_profiles
  |  1---* health_goals
  |  1---* meal_logs 1---* food_items
  |  1---* exercise_logs
  |  1---* sleep_logs
  |  1---* ai_runs
  |  1---* recommendations
  |  1---* health_plans 1---* plan_items
  |  1---* consent_records
  |  1---* files
  |  1---* export_requests
  |
  *---* households (through household_members)

sharing_permissions -> owner_user + grantee_user + resource scope (future)
audit_events -> actor + action + target metadata (no health content)
```

## 3. 表草案

### 身份与档案

`users`

- `id uuid PK`
- `oidc_issuer text NOT NULL`
- `oidc_subject text NOT NULL`
- `status text CHECK (active, deletion_pending, deleted)`
- `timezone text NOT NULL`
- `locale text NOT NULL`
- `created_at`, `updated_at`, `deleted_at`
- UNIQUE (`oidc_issuer`, `oidc_subject`)

`health_profiles`

- `user_id uuid PK/FK users`
- `birth_year smallint NULL`（MVP 不采集完整生日，除非确有必要）
- `sex_for_health_context text NULL`
- `height_cm numeric(5,2) NULL`
- `weight_kg numeric(5,2) NULL`
- `dietary_preferences jsonb NOT NULL DEFAULT '[]'`
- `allergies jsonb NOT NULL DEFAULT '[]'`
- `exercise_limitations text NULL`
- `version int NOT NULL`
- timestamps

`health_goals`

- `id`, `user_id`, `goal_type`, `target_value`, `unit`
- `start_date`, `target_date`, `status`, timestamps

自由文本字段需要更严格的展示、日志和 AI 发送策略。

### 记录

`meal_logs`

- `id`, `user_id`
- `occurred_at timestamptz NOT NULL`
- `meal_type text NULL`
- `status text CHECK (draft, processing, needs_confirmation, confirmed, failed)`
- `source text CHECK (manual, photo_ai, import)`
- `photo_file_id uuid NULL`
- `confirmed_at timestamptz NULL`
- `notes text NULL`
- `version int`, timestamps, `deleted_at`

`food_items`

- `id`, `meal_log_id`, `user_id`（冗余所有者便于 RLS 与安全索引）
- `name`, `quantity`, `unit`
- `calories_kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`（均可空）
- `origin text CHECK (ai_estimate, user_added, user_corrected)`
- `ai_item_id text NULL`（关联结构化 AI 草稿，不暴露 provider ID）
- timestamps

`exercise_logs`

- `id`, `user_id`, `exercise_type`, `started_at`, `duration_minutes`
- `intensity text`, `steps int NULL`, `notes`, `source`, timestamps, `deleted_at`

`sleep_logs`

- `id`, `user_id`, `started_at`, `ended_at`
- `quality_score smallint CHECK 1..5`, `notes`, `source`, timestamps, `deleted_at`
- CHECK (`ended_at > started_at`)

### AI 与计划

`ai_runs`

- `id`, `user_id`, `purpose`
- `provider_alias`, `model_alias`, `prompt_version`, `schema_version`
- `input_digest`（最小摘要的不可逆摘要，用于追踪，不保存普通日志）
- `redacted_input jsonb NULL`（仅在有明确保留目的和期限时保存）
- `raw_output_encrypted bytea/object_ref NULL`
- `parsed_output jsonb NULL`
- `status`, `latency_ms`, `token_usage jsonb`, `estimated_cost`
- `consent_record_id`, `retention_until`, timestamps

`recommendations`

- `id`, `user_id`, `ai_run_id`, `period_start`, `period_end`
- `kind text CHECK (daily, weekly_summary)`
- `content jsonb`, `evidence_refs jsonb`, `status`, timestamps

`health_plans`

- `id`, `user_id`, `source_ai_run_id NULL`
- `week_start date`, `status text CHECK (draft, confirmed, archived)`
- `version`, `confirmed_at`, timestamps

`plan_items`

- `id`, `health_plan_id`, `user_id`, `category`, `scheduled_date`
- `action_text`, `rationale`, `status`, `user_feedback`, timestamps

### 文件、同意和用户权利

`files`

- `id`, `user_id`, `purpose`, `storage_key`（随机且唯一）
- `original_filename_encrypted NULL`, `declared_mime`, `detected_mime`
- `size_bytes`, `sha256`, `status`, `derived_from_file_id NULL`
- `retention_until`, timestamps, `deleted_at`

`consent_records`

- `id`, `user_id`, `purpose`, `policy_version`
- `decision text CHECK (granted, withdrawn)`
- `decided_at`, `context jsonb`（不存不必要指纹）

`export_requests`

- `id`, `user_id`, `status`, `file_id NULL`, `expires_at`, timestamps

`deletion_requests`

- `id`, `user_id`, `scope`, `status`, `requested_at`, `completed_at`
- `backup_expiry_at`, `failure_reason_code NULL`

### 家庭与共享（只建边界，MVP 不开放共享）

`households`: `id`, `name`, timestamps

`household_members`: `household_id`, `user_id`, `role`, `status`, timestamps

`sharing_permissions`（功能实现时再创建迁移）：

- owner、grantee、资源类型/范围、权限、有效期、撤销时间
- 明确禁止 `household_id` 本身授予读取权限

### 审计与任务

`audit_events`

- `id`, `occurred_at`, `actor_type`, `actor_id NULL`
- `action`, `target_type`, `target_id NULL`, `outcome`
- `request_id`, `ip_prefix_or_hash NULL`, `metadata jsonb`
- 追加式写入；`metadata` 不得包含健康正文、Token 或原始 AI 内容

`jobs`

- `id`, `job_type`, `owner_user_id NULL`, `idempotency_key UNIQUE`
- `payload jsonb`, `status`, `attempts`, `available_at`, `lease_until`
- `last_error_code`, timestamps

## 4. 索引策略

- 所有用户数据：`(user_id, occurred_at DESC)` 或 `(user_id, created_at DESC)`。
- 活跃记录使用 `WHERE deleted_at IS NULL` 的部分索引。
- 每周计划：UNIQUE (`user_id`, `week_start`) WHERE status != 'archived'（具体产品行为确认后定）。
- 文件：UNIQUE (`storage_key`)，以及 `(user_id, status, created_at)`。
- Job：`(status, available_at)` WHERE status = 'queued'。
- 审计：`(actor_id, occurred_at)`、`(target_type, target_id, occurred_at)`。

避免为低基数字段单独建索引；用真实查询和 `EXPLAIN ANALYZE` 验证。

## 5. RLS 示例策略

每个事务在验证身份后设置只读事务上下文，如 `app.current_user_id`。示意：

```sql
ALTER TABLE meal_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE meal_logs FORCE ROW LEVEL SECURITY;

CREATE POLICY meal_owner_policy ON meal_logs
USING (user_id = current_setting('app.current_user_id', true)::uuid)
WITH CHECK (user_id = current_setting('app.current_user_id', true)::uuid);
```

实现要求：

- API 连接角色不是表所有者，无 `BYPASSRLS`。
- 使用连接池时每个事务设置并在事务结束自动清理上下文。
- Migration 角色与运行时角色分离。
- 自动测试跨用户 SELECT/UPDATE/DELETE 和通过关联表的间接访问。
- RLS 不能替代应用层授权；两层都需要测试。

## 6. 数据保留

最终期限在选定部署地域和供应商后确认。MVP 至少做到：

- 上传失败或未关联文件自动清理。
- 预签名 URL 分钟级过期。
- 导出包短期保留，到期自动删除。
- AI 原始输出采用最短可行保留期，与确认记录分离。
- 账号删除后生产数据按流程清除；加密备份随轮换周期淘汰并记录最终日期。
- 审计数据只保存必要元数据，并有独立保留策略。
