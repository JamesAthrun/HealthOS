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
invitations 1---0..1 users
users 1---1 health_profiles
  |  1---1 user_preferences
  |  1---* health_goals
  |  1---* meal_logs 1---* food_items
  |                  1---* meal_recognitions *---1 ai_runs
  |  1---* exercise_logs
  |  1---* sleep_logs
  |  1---* ai_runs
  |  1---* recommendations
  |  1---* health_plans 1---* plan_items
  |  1---* consent_records
  |  1---* files
  |  1---* export_requests
  |  1---* deletion_requests
  |
  *---* households (through household_members)

sharing_permissions -> owner_user + grantee_user + resource scope (future)
audit_events -> actor + action + target metadata (no health content)
web.sessions -> BFF 会话（独立 schema 与角色）
```

数据库布局：同一 PostgreSQL 实例内，业务表位于 `healthos` 数据库的 `app` schema；BFF 会话位于 `web` schema；Logto 使用独立的 `logto` 数据库。各自使用独立角色，互不授权（见系统设计“数据库角色”）。

## 3. 表草案

### 身份与档案

`invitations`（D-002）

- `id uuid PK`
- `email_normalized text NOT NULL`
- `token_hash bytea NOT NULL UNIQUE`（只保存 SHA-256，明文 token 仅出现在邮件中）
- `invited_by_user_id uuid NULL`（首个管理员由部署脚本创建）
- `status text CHECK (pending, accepted, revoked, expired)`
- `expires_at timestamptz NOT NULL`（创建后 7 天）
- `accepted_user_id uuid NULL`, `accepted_at`, timestamps
- 不启用 RLS（无健康数据），只允许身份模块和管理脚本访问

`users`

- `id uuid PK`
- `oidc_issuer text NOT NULL`
- `oidc_subject text NOT NULL`
- `status text CHECK (active, deletion_pending, deleted)`
- `role text CHECK (member, admin) DEFAULT 'member'`（admin 只能管理邀请，不能查看他人健康数据）
- `timezone text NOT NULL DEFAULT 'Asia/Shanghai'`
- `locale text NOT NULL DEFAULT 'zh-CN'`
- `created_at`, `updated_at`, `deleted_at`
- UNIQUE (`oidc_issuer`, `oidc_subject`)

`user_preferences`

- `user_id uuid PK/FK users`
- `auto_daily_advice boolean NOT NULL DEFAULT false`
- `auto_weekly_plan boolean NOT NULL DEFAULT false`
- `version int NOT NULL`, timestamps

`health_profiles`

- `user_id uuid PK/FK users`
- `birth_year smallint NOT NULL`（不采集完整生日；应用层校验年龄 ≥ 18，D-006）
- `sex_for_health_context text NULL CHECK (male, female, undisclosed)`
- `height_cm numeric(5,2) NULL CHECK (100..250)`
- `weight_kg numeric(5,2) NULL CHECK (30..300)`
- `activity_level text NULL CHECK (sedentary, light, moderate, active)`
- `pregnant_or_lactating boolean NOT NULL DEFAULT false`
- `dietary_preferences jsonb NOT NULL DEFAULT '[]'`
- `allergies jsonb NOT NULL DEFAULT '[]'`
- `exercise_limitation_tags jsonb NOT NULL DEFAULT '[]'`（预置标签，如 `knee`、`lower_back`、`avoid_high_impact`，可发送给 AI）
- `exercise_limitations text NULL`（最长 500 字，自由文本默认不发送给 AI）
- `version int NOT NULL`
- timestamps

`health_goals`

- `id`, `user_id`
- `goal_type text CHECK (weight_kg, daily_energy_kcal, daily_protein_g, weekly_exercise_minutes, nightly_sleep_hours, daily_steps)`
- `direction text CHECK (lose, maintain, gain) NULL`（仅体重和热量目标使用）
- `target_value numeric NOT NULL`, `unit text NOT NULL`
- `source text CHECK (user, formula)`
- `formula_version text NULL`（如 `nutrition_formula_v1`，D-008）
- `formula_inputs jsonb NULL`（计算时的体重、身高、年龄、活动水平快照）
- `confirmed_at timestamptz NULL`（`source = formula` 时必须由用户确认后才生效）
- `start_date`, `target_date NULL`
- `status text CHECK (active, achieved, archived)`, `version`, timestamps
- 同一用户同一 `goal_type` 只能有一个 `active` 目标（部分唯一索引）

自由文本字段需要更严格的展示、日志和 AI 发送策略。

### 记录

`meal_logs`

- `id`, `user_id`
- `occurred_at timestamptz NOT NULL`
- `meal_type text NULL CHECK (breakfast, lunch, dinner, snack)`
- `status text CHECK (draft, processing, needs_confirmation, confirmed, failed)`
- `source text CHECK (manual, photo_ai, import)`
- `photo_file_id uuid NULL`
- `confirmed_at timestamptz NULL`
- `notes text NULL`（最长 500 字）
- `version int`, timestamps, `deleted_at`

状态机：

```text
draft --(发起识别)--> processing --(成功)--> needs_confirmation --(确认)--> confirmed
  |                         |                         |
  |                         +--(失败)--> failed ------+--(手工确认)--> confirmed
  +--------------------(手工确认)---------------------------------------> confirmed
confirmed --(用户修改并重新确认)--> confirmed（version + 1）
```

只有 `confirmed` 且未软删除的记录进入统计。

`meal_recognitions`（AI 草稿，与确认值分离）

- `id`, `meal_log_id`, `user_id`, `ai_run_id`, `job_id`
- `status text CHECK (queued, running, succeeded, failed, cancelled)`
- `draft_items jsonb NULL`（通过校验的结构化识别结果，每项带稳定 `draft_item_id`）
- `overall_confidence text NULL CHECK (low, medium, high)`
- `failure_code text NULL`, timestamps
- 同一餐可以重新识别；确认时引用的是最新一次 `succeeded` 的识别结果

`food_items`（仅保存确认时提交的最终项）

- `id`, `meal_log_id`, `user_id`（冗余所有者便于 RLS 与安全索引）
- `name`（最长 100 字）, `quantity`, `unit`
- `calories_kcal`, `protein_g`, `carbs_g`, `fat_g`, `fiber_g`（均可空，非负）
- `origin text CHECK (ai_estimate, user_added, user_corrected)`
- `recognition_id uuid NULL`, `draft_item_id text NULL`（关联 AI 草稿项，用于计算修正率）
- timestamps
- 确认操作在同一事务内用提交的完整列表替换该餐的全部 `food_items`，并把 `meal_logs.version` 加 1；每餐最多 30 项

`exercise_logs`

- `id`, `user_id`, `exercise_type text`（预置列表 + `other`）, `started_at`
- `duration_minutes int CHECK (1..1440)`
- `intensity text CHECK (low, moderate, high)`, `steps int NULL CHECK (0..100000)`
- `notes`, `source`, `version int`, timestamps, `deleted_at`

`sleep_logs`

- `id`, `user_id`, `started_at`, `ended_at`
- `quality_score smallint CHECK 1..5`, `notes`, `source`, `version int`, timestamps, `deleted_at`
- CHECK (`ended_at > started_at` AND `ended_at - started_at <= interval '24 hours'`)
- 归属日期：按用户时区下 `ended_at` 的本地日期计入“昨晚睡眠”；同一用户的睡眠时段不得重叠（应用层校验，可用 `EXCLUDE USING gist` 加强）

### AI 与计划

`ai_runs`

- `id`, `user_id`, `purpose text CHECK (meal_recognition, daily_advice, weekly_plan)`
- `provider_alias`, `model_alias`, `provider_model_version`（响应中返回的实际版本）, `prompt_version`, `schema_version`
- `input_digest`（最小摘要的不可逆摘要，用于追踪，不保存普通日志）
- `redacted_input jsonb NULL`（仅在有明确保留目的和期限时保存）
- `raw_output_encrypted bytea/object_ref NULL`
- `parsed_output jsonb NULL`
- `status`, `latency_ms`, `token_usage jsonb`, `estimated_cost`
- `consent_record_id`, `retention_until`, timestamps

`recommendations`

- `id`, `user_id`, `ai_run_id NULL`（安全降级时使用确定性通用建议，可为空）
- `kind text CHECK (daily)`（周计划说明保存在 `health_plans`）
- `target_local_date date NOT NULL`（建议面向的日期）
- `period_start`, `period_end`（输入数据区间）
- `content jsonb`, `evidence_refs jsonb`, `limitations jsonb`
- `status text CHECK (active, superseded)`
- `feedback text NULL CHECK (useful, not_applicable, unsafe)`, `feedback_at`
- timestamps
- UNIQUE (`user_id`, `kind`, `target_local_date`) WHERE status = 'active'

`health_plans`

- `id`, `user_id`, `source_ai_run_id NULL`
- `week_start date NOT NULL`（周一）, `status text CHECK (draft, confirmed, archived)`
- `summary text NULL`, `limitations jsonb`
- `version`, `confirmed_at`, timestamps
- AI 原始草稿保存在 `ai_runs.parsed_output`；`plan_items` 是可编辑副本

`plan_items`

- `id`, `health_plan_id`, `user_id`
- `category text CHECK (diet, exercise, sleep)`, `scheduled_date date NULL`
- `action_text`（最长 200 字）, `rationale`, `evidence_refs jsonb`
- `origin text CHECK (ai, user_added, user_edited)`
- `status text CHECK (pending, done, skipped, not_applicable)`
- `user_feedback text NULL`, `sort_order int`, timestamps

### 文件、同意和用户权利

`files`

- `id`, `user_id`, `purpose`, `storage_key`（随机且唯一）
- `original_filename_encrypted NULL`, `declared_mime`, `detected_mime`
- `size_bytes`, `sha256`, `status`, `derived_from_file_id NULL`
- `retention_until`, timestamps, `deleted_at`

`consent_records`（追加式，最新一条决定当前状态）

- `id`, `user_id`
- `purpose text CHECK (terms_of_service, sensitive_health_data_processing, meal_photo_ai_analysis, health_summary_ai_planning)`
- `policy_version`
- `decision text CHECK (granted, withdrawn)`
- `decided_at`, `context jsonb`（不存不必要指纹）
- `sensitive_health_data_processing` 对应 PIPL 敏感个人信息单独同意；未授予时不能创建健康档案和记录

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
- `payload jsonb`, `status text CHECK (queued, running, succeeded, failed, dead, cancelled)`
- `attempts`, `max_attempts`, `available_at`, `lease_until`
- `last_error_code`, `result_ref jsonb NULL`（指向结果资源 ID，不存结果正文）, timestamps
- 不启用 RLS；API 只通过带 `owner_user_id` 条件的查询向用户暴露任务状态

### BFF 会话（`web` schema）

`web.sessions`

- `id_hash bytea PK`（Cookie 中随机 ID 的 SHA-256）
- `oidc_subject text NOT NULL`
- `tokens_encrypted bytea NOT NULL`（AES-GCM，密钥来自 Secret）
- `auth_time timestamptz`, `last_seen_at`, `idle_expires_at`, `absolute_expires_at`
- `revoked_at NULL`, `user_agent_hash NULL`
- 仅 `healthos_web` 角色可访问；不包含任何健康数据

## 4. 索引策略

- 所有用户数据：`(user_id, occurred_at DESC)` 或 `(user_id, created_at DESC)`。
- 活跃记录使用 `WHERE deleted_at IS NULL` 的部分索引。
- 每周计划：UNIQUE (`user_id`, `week_start`) WHERE status IN ('draft', 'confirmed')。重新生成草稿时先把旧草稿置为 `archived`；已确认的计划需要用户先归档才能重新生成。
- 健康目标：UNIQUE (`user_id`, `goal_type`) WHERE status = 'active'。
- 邀请：UNIQUE (`email_normalized`) WHERE status = 'pending'。
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

具体期限见 [DECISIONS.md](DECISIONS.md) 的 D-014。实现要求：

- 每类可过期数据都有 `retention_until` 或可推导的过期时间，并由清理任务处理。
- 清理任务幂等，先删除对象存储中的文件，再删除或标记数据库元数据，失败可重试。
- 账号删除覆盖：业务表、文件（含派生文件）、导出包、AI 原始输出、待处理任务、BFF 会话和 Logto 用户；审计事件只保留元数据，并把 `actor_id` 替换为不可逆假名。
- 加密备份随轮换周期淘汰；从备份恢复后必须重放删除清单。
