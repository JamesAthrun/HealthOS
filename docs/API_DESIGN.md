# HealthOS REST API 设计 v0.1

## 1. 约定

- Base path: `/api/v1`
- JSON 字段使用 `snake_case`；时间为 ISO 8601 UTC，响应以 `Z` 表示。
- OIDC Bearer Token 或安全 BFF 会话；具体浏览器架构在实现阶段定稿。
- 客户端不得提交 `user_id` 作为资源所有者。
- 创建接口支持 `Idempotency-Key`；更新使用 `If-Match`/版本号防止丢失更新。
- 列表使用 opaque cursor，不使用大 offset。
- 删除默认返回 `204`；异步导出/删除返回 `202`。
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

## 3. 端点

### 会话与用户

- `GET /me` — 当前用户和产品设置
- `PATCH /me` — 时区、locale 等非敏感设置
- `POST /me/export-requests` — 请求数据导出
- `GET /me/export-requests/{id}` — 查询导出状态
- `POST /me/deletion-requests` — 重新验证后请求删除账号
- `GET /me/deletion-requests/{id}` — 查询删除状态

### 档案与目标

- `GET /profile`
- `PUT /profile`
- `GET /goals`
- `POST /goals`
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
- `POST /meals/{meal_id}/recognition-jobs` — 在有效同意下发起识别
- `GET /meals/{meal_id}/recognition-jobs/{job_id}`
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
- `POST /recommendations/daily-jobs` — 生成指定本地日期的次日建议
- `GET /recommendations?kind=&from=&to=`
- `GET /recommendations/{id}`
- `POST /plans/weekly-jobs` — 生成计划草稿
- `GET /plans?week_start=`
- `GET /plans/{plan_id}`
- `PATCH /plans/{plan_id}` — 用户编辑草稿
- `POST /plans/{plan_id}/confirm`
- `PATCH /plans/{plan_id}/items/{item_id}` — 完成状态和反馈

### 同意

- `GET /consents` — 当前决定和政策版本
- `POST /consents` — 对某目的授予或撤回同意

可用 purpose：`meal_photo_ai_analysis`、`health_summary_ai_planning`。同意不能捆绑；撤回影响未来处理，并触发适用的保留清理流程。

## 4. 权限矩阵

| 资源 | 本人 | 其他用户 | 后台任务 |
| --- | --- | --- | --- |
| 档案/记录 | CRUD | 无 | 按任务只读/写特定结果 |
| 文件 | 本人、短时访问 | 无 | 仅处理目标文件 |
| AI 草稿 | 读取本人可展示版本 | 无 | 创建/更新任务结果 |
| 审计 | 仅产品允许的本人事件摘要 | 无 | 追加，不可修改 |
| 导出/删除 | 发起并查询本人请求 | 无 | 执行指定请求 |

## 5. API 安全要求

- CORS 只允许明确前端 Origin；有 Cookie 时启用 CSRF 防护。
- 按用户、IP 风险和端点成本限流，AI/导出/登录相关端点更严格。
- 所有输入限制长度、范围、嵌套深度和列表数量。
- 文件依据实际内容而非扩展名判断。
- 任何返回 URL 不暴露永久对象键或长期凭据。
- OpenAPI 示例仅使用合成数据。

## 6. 版本演进

MVP 使用 URL 主版本。新增可选字段属于兼容变化；删除/改名/语义变化先发布迁移期。异步任务和 AI 结果携带独立 `schema_version`，避免 API 版本与内部模型耦合。
