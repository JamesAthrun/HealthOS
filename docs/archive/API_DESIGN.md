# HealthOS REST API 设计 v0.1

## 1. 约定

- Base path: `/api/v1`（浏览器访问 `https://<domain>/api/v1/*`，由 Next.js BFF 转发到内部 FastAPI）
- JSON 字段使用 `snake_case`；时间为 ISO 8601 UTC，响应以 `Z` 表示；本地日期字段使用 `YYYY-MM-DD` 并按用户时区解释。
- 认证采用 BFF（D-005）：浏览器只携带 `__Host-healthos_session` Cookie；BFF 向 FastAPI 发送 `Authorization: Bearer <access_token>`。FastAPI 不接受 Cookie。
- 改变状态的请求（POST/PUT/PATCH/DELETE）必须携带 `X-HealthOS-CSRF`，BFF 同时校验 `Origin`。
- 客户端不得提交 `user_id` 作为资源所有者。
- 创建接口支持 `Idempotency-Key`；更新使用 `If-Match`/版本号防止丢失更新。
- 列表使用 opaque cursor，不使用大 offset。
- 删除默认返回 `204`；异步任务（识别、建议、计划、导出、删除）返回 `202` 和 `{"job_id": "..."}`，统一通过 `GET /jobs/{job_id}` 轮询（D-011）。
- OpenAPI 是契约来源，CI 检查破坏性变更并生成前端类型。

## 2. 响应与错误

成功单资源直接返回资源对象；列表：

```json
{
  "items": [],
  "next_cursor": null
}
```

错误遵循 Problem Details 风格：

```json
{
  "type": "https://healthos.local/problems/validation-error",
  "title": "Request validation failed",
  "status": 422,
  "code": "INVALID_SLEEP_RANGE",
  "detail": "The sleep end time must be after the start time.",
  "request_id": "req_...",
  "fields": [{"field": "ended_at", "code": "after_start_required"}]
}
```

生产错误不返回堆栈、SQL、对象键、模型原始输出或其他用户资源是否存在。对越权资源使用一致的 404 策略。

常用错误码：

| HTTP | `code` | 含义 |
| --- | --- | --- |
| 401 | `UNAUTHENTICATED` | 会话不存在或已过期 |
| 401 | `REAUTH_REQUIRED` | 敏感操作要求 10 分钟内重新登录 |
| 403 | `CONSENT_REQUIRED` | 缺少对应用途的有效同意 |
| 403 | `ONBOARDING_REQUIRED` | 尚未完成敏感信息同意或年龄确认 |
| 404 | `NOT_FOUND` | 资源不存在或无权访问（不区分） |
| 409 | `VERSION_CONFLICT` | `If-Match` 版本不匹配 |
| 409 | `INVALID_STATE` | 当前状态不允许该操作（如重复确认） |
| 422 | 各字段校验码 | 输入校验失败 |
| 429 | `RATE_LIMITED` | 触发限流，携带 `Retry-After` |
| 503 | `AI_UNAVAILABLE` / `AI_BUDGET_EXHAUSTED` | AI 暂不可用或预算耗尽 |

## 3. 端点

### BFF 认证路由（Next.js，不属于 `/api/v1`）

- `GET /auth/login` — 发起 OIDC 登录（PKCE、state、nonce）
- `GET /auth/callback` — 处理回调、创建服务端会话、签发 Cookie
- `POST /auth/logout` — 撤销会话并结束 Logto 会话
- `GET /auth/reauth?return_to=` — 以 `max_age=600` 重新认证；`return_to` 只允许站内相对路径
- `GET /invite/{token}` — 展示邀请说明并引导登录

### 任务

- `GET /jobs/{job_id}` — 本人任务状态：`status`、`result_ref`、安全的 `failure_code`

### 邀请（仅 `admin` 角色）

- `POST /admin/invitations` — 创建邀请并发送邮件
- `GET /admin/invitations` — 查看邀请状态（不含任何健康数据）
- `DELETE /admin/invitations/{invitation_id}` — 撤销未使用邀请

### 会话与用户

- `GET /me` — 当前用户、引导状态和产品设置
- `PATCH /me` — 时区、locale 等非敏感设置
- `GET /me/preferences`
- `PATCH /me/preferences` — 自动生成每日建议/每周计划开关
- `POST /me/export-requests` — 请求数据导出（需重新认证）
- `GET /me/export-requests/{id}` — 查询导出状态
- `POST /me/export-requests/{id}/download-url` — 获取 5 分钟有效的下载链接
- `POST /me/deletion-requests` — 重新验证后请求删除账号
- `GET /me/deletion-requests/{id}` — 查询删除状态

### 档案与目标

- `GET /profile`
- `PUT /profile`
- `GET /profile/nutrition-reference` — 按 `nutrition_formula_v1` 返回参考值、输入快照和触发的护栏；缺少必要字段时返回 `available: false` 及原因（D-008）
- `GET /goals`
- `POST /goals` — `source: "formula"` 时必须携带参考值接口返回的 `formula_version` 与输入快照，服务端重新计算校验
- `PATCH /goals/{goal_id}`
- `DELETE /goals/{goal_id}`

### 文件

- `POST /file-uploads` — 创建上传会话
- `POST /file-uploads/{upload_id}/complete` — 通知完成并进入校验
- `GET /files/{file_id}` — 获取元数据
- `POST /files/{file_id}/download-url` — 获取本人文件短期访问 URL
- `DELETE /files/{file_id}` — 删除未被记录引用或按级联策略处理

### 饮食

- `GET /meals?from=&to=&cursor=`
- `POST /meals` — 手工草稿或关联已就绪图片
- `GET /meals/{meal_id}`
- `PATCH /meals/{meal_id}`
- `DELETE /meals/{meal_id}`
- `DELETE /meals/{meal_id}/photo` — 只删除照片，保留已确认的食物项
- `POST /meals/{meal_id}/recognition-jobs` — 在有效同意下发起识别，返回 `202` + `job_id`
- `GET /meals/{meal_id}/recognitions/latest` — 最新识别草稿（仅展示用，不计入统计）
- `POST /meals/{meal_id}/confirm` — 提交最终食物项并确认

`POST /meals` 示例：

```json
{
  "occurred_at": "2026-10-29T04:30:00Z",
  "meal_type": "lunch",
  "photo_file_id": "019...",
  "notes": null
}
```

确认操作必须包含当前版本和完整确认项，避免把旧 AI 结果与新编辑混合。

`POST /meals/{meal_id}/confirm` 示例：

```json
{
  "version": 3,
  "recognition_id": "019...",
  "items": [
    {
      "draft_item_id": "d1",
      "origin": "user_corrected",
      "name": "番茄炒蛋",
      "quantity": 150,
      "unit": "g",
      "calories_kcal": 180,
      "protein_g": 10,
      "carbs_g": 6,
      "fat_g": 13,
      "fiber_g": 1
    },
    {
      "draft_item_id": null,
      "origin": "user_added",
      "name": "米饭",
      "quantity": 1,
      "unit": "碗",
      "calories_kcal": 230
    }
  ]
}
```

服务端校验：`recognition_id` 属于该餐且为最新成功识别；`draft_item_id` 必须存在于该草稿；`items` 最多 30 项；营养数值非负且有合理上限。

### 运动

- `GET /exercises?from=&to=&cursor=`
- `POST /exercises`
- `GET /exercises/{exercise_id}`
- `PATCH /exercises/{exercise_id}`
- `DELETE /exercises/{exercise_id}`

### 睡眠

- `GET /sleep-logs?from=&to=&cursor=`
- `POST /sleep-logs`
- `GET /sleep-logs/{sleep_id}`
- `PATCH /sleep-logs/{sleep_id}`
- `DELETE /sleep-logs/{sleep_id}`

### 看板、建议和计划

- `GET /dashboard/daily?date=YYYY-MM-DD`
- `GET /dashboard/trends?from=&to=`（MVP 最长 31 天）
- `POST /recommendations/daily-jobs` — 为指定 `target_local_date` 生成建议（默认明天），返回 `202` + `job_id`
- `GET /recommendations?kind=&from=&to=`
- `GET /recommendations/{id}`
- `POST /recommendations/{id}/feedback` — `useful` / `not_applicable` / `unsafe`
- `POST /plans/weekly-jobs` — 为指定 `week_start`（周一）生成计划草稿，返回 `202` + `job_id`
- `GET /plans?week_start=`
- `GET /plans/{plan_id}`
- `PATCH /plans/{plan_id}` — 用户编辑草稿（增删改计划项）
- `POST /plans/{plan_id}/confirm`
- `POST /plans/{plan_id}/archive` — 归档后可重新生成该周计划
- `PATCH /plans/{plan_id}/items/{item_id}` — 完成状态和反馈

### 同意

- `GET /consents` — 当前决定和政策版本
- `POST /consents` — 对某目的授予或撤回同意

可用 purpose：

| purpose | 含义 | 未授予时 |
| --- | --- | --- |
| `terms_of_service` | 服务条款与隐私政策 | 无法使用 |
| `sensitive_health_data_processing` | PIPL 敏感个人信息单独同意 | 不能创建档案和记录 |
| `meal_photo_ai_analysis` | 将餐食照片发送给 AI 识别 | 只能手工记录 |
| `health_summary_ai_planning` | 将健康摘要发送给 AI 生成建议和计划 | 不生成 AI 建议 |

同意不能捆绑；撤回影响未来处理，取消待执行的相关任务，并触发适用的保留清理流程。撤回 `sensitive_health_data_processing` 等同于停止使用，界面引导用户导出并删除账号。

### 健康检查（仅内部网络）

- `GET /health/live` — 进程存活
- `GET /health/ready` — 数据库、对象存储和 JWKS 可用；只返回 `ok`/`degraded`，不含细节

这两个端点不在 `/api/v1` 下，Reverse proxy 不对公网转发。

## 4. 权限矩阵

| 资源 | 本人 | 其他用户 | admin | 后台任务 |
| --- | --- | --- | --- | --- |
| 档案/记录 | CRUD | 无 | 无 | 按任务只读/写特定结果 |
| 文件 | 本人、短时访问 | 无 | 无 | 仅处理目标文件 |
| AI 草稿 | 读取本人可展示版本 | 无 | 无 | 创建/更新任务结果 |
| 审计 | 仅产品允许的本人事件摘要 | 无 | 无 | 追加，不可修改 |
| 导出/删除 | 发起并查询本人请求 | 无 | 无 | 执行指定请求 |
| 邀请 | 无 | 无 | 创建/查看/撤销 | 发送邮件、过期清理 |

## 5. API 安全要求

- FastAPI 只在内部网络监听；公网 CORS 由 BFF 同源访问自然解决，不开放跨域。
- 按用户、IP 风险和端点成本限流（MVP 初始值，试运行中调整）：

| 端点类别 | 限制 |
| --- | --- |
| BFF 登录/回调/邀请 | 每 IP 10 次/分钟 |
| 普通读写 | 每用户 120 次/分钟 |
| 文件上传会话 | 每用户 20 次/小时 |
| 饮食识别 | 每用户 30 次/天 |
| 每日建议 / 每周计划 | 每用户各 5 次/天 |
| 导出 | 每用户 3 次/天 |

- 所有输入限制长度、范围、嵌套深度和列表数量。
- 文件依据实际内容而非扩展名判断。
- 任何返回 URL 不暴露永久对象键或长期凭据。
- OpenAPI 示例仅使用合成数据。

## 6. 版本演进

MVP 使用 URL 主版本。新增可选字段属于兼容变化；删除/改名/语义变化先发布迁移期。异步任务和 AI 结果携带独立 `schema_version`，避免 API 版本与内部模型耦合。
