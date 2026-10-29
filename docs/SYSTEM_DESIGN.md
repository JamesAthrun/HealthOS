# HealthOS 系统设计 v0.1

## 1. 设计目标

在单台服务器即可可靠运行的前提下，建立可测试、可恢复、默认私密的模块化单体。未来增加报告、设备、共享或订阅时，优先增加模块和异步集成，而不是改写数据所有权模型。

## 2. 系统上下文

```text
Mobile/Desktop Browser
        |
      HTTPS
        v
  Reverse Proxy / WAF
        |
  +-----+-----------------------+
  | Next.js Web                 |
  | FastAPI REST API            |
  | Background Worker           |
  +-----+-------------+---------+
        |             |
   PostgreSQL     Private S3
        |             |
        +------ AI Gateway ---- External/Local AI Provider

External: OIDC identity provider, email provider (optional)
Operations: metrics, error tracking, encrypted backup target
```

浏览器不直接访问数据库、内部对象存储或 AI Provider。文件下载通过 API 授权后签发短期 URL，或由 API 代理返回。

## 3. 逻辑模块

| 模块 | 职责 | 不负责 |
| --- | --- | --- |
| Identity & Access | OIDC 身份映射、会话、主体和授权策略 | 保存密码、业务数据共享 |
| Profiles | 健康档案、目标、偏好和限制 | 诊断或医疗建议 |
| Records | 饮食、食物项、运动、睡眠 CRUD | 调用外部模型 |
| Files | 上传会话、校验、元数据、访问授权和生命周期 | 解析业务语义 |
| AI Gateway | Provider 适配、最小化、结构校验、版本和成本 | 决定最终业务记录 |
| Planning | 聚合数据、每日建议、每周计划、反馈 | 直接读取其他用户数据 |
| Consent & Privacy | 同意版本、导出、删除工作流 | 绕过保留策略 |
| Audit | 追加式安全事件 | 保存完整健康正文或密钥 |
| Jobs | 异步任务、重试、幂等和死信 | 承载未授权的长期凭据 |

模块通过应用服务接口或领域事件协作，禁止跨模块直接依赖别人的 ORM 内部实现。初期可以共用数据库，但各模块拥有明确的表和迁移责任。

## 4. 代码结构建议

```text
backend/app/
├── api/                 # 路由、请求/响应模型
├── core/                # 配置、数据库、鉴权、日志
├── modules/
│   ├── identity/
│   ├── profiles/
│   ├── records/
│   ├── files/
│   ├── ai_gateway/
│   ├── planning/
│   ├── privacy/
│   └── audit/
├── jobs/                # Worker 入口和任务注册
└── main.py

frontend/src/
├── app/                 # Next.js routes/layouts
├── features/            # profile, meals, activity, sleep, planning
├── components/          # 通用无业务 UI
├── lib/                 # API client, auth, validation, telemetry
└── types/               # 生成或共享的 API 类型
```

## 5. 身份与授权

1. 使用成熟 OIDC 服务；Web 采用 Authorization Code + PKCE。
2. API 验证 issuer、audience、签名、有效期和必要声明。
3. 首次登录创建内部用户，外部 subject 与内部 UUID 唯一映射。
4. 服务端从认证上下文获得用户 ID；资源路由中的 ID 只代表资源，不代表所有者。
5. Repository 查询必须同时包含资源 ID 和所有者 ID。
6. PostgreSQL RLS 作为纵深防御；应用连接角色不得是表所有者或 `BYPASSRLS`。
7. 后台任务使用显式服务主体和最小权限，任务载荷携带目标用户及授权原因，执行全程审计。

## 6. 数据与事务

- PostgreSQL 是结构化业务数据的唯一事实来源。
- 对象存储只保存加密文件；数据库保存所有者、用途、哈希、状态和对象键。
- 所有主键使用 UUIDv7（实现环境不支持时使用 UUIDv4）。
- 时间以 UTC 保存，同时在用户档案中保存 IANA 时区；统计按用户本地日计算。
- `created_at`、`updated_at` 使用数据库时间；更新采用乐观锁或版本号避免覆盖。
- 删除业务记录先进入软删除和审计流程，随后由生命周期任务物理清理；法定或安全审计记录按单独策略保留。
- AI 草稿与用户确认记录分别建模，不直接覆盖。

## 7. 文件上传流程

```text
Client -> POST /file-uploads (用途、类型、大小)
API -> 验证配额/类型，创建 pending metadata
API -> 返回短时预签名上传信息
Client -> Private S3
Client -> POST /file-uploads/{id}/complete
Worker -> 校验实际大小、MIME、magic bytes、哈希、像素/解码安全
Worker -> 标记 ready 或 quarantined
Records -> 仅引用 ready 且属于当前用户的文件
```

上传对象键不可包含用户提供的文件名。图片解析应在资源受限环境中进行，移除非必要 EXIF（特别是地理位置），原始文件和派生文件分别记录。

## 8. 异步任务

MVP 使用独立 Worker 进程和数据库任务表，避免一开始引入 Redis/Celery。任务必须：

- 有稳定幂等键，重复执行不会产生重复记录或重复计费。
- 状态为 queued/running/succeeded/failed/dead，记录尝试次数和下次执行时间。
- 指数退避并限制重试；不可重试错误直接失败。
- 任务载荷不存原始图片、Token 或完整健康档案。
- Worker 失效后可通过租约超时重新领取任务。

当任务吞吐或调度需求达到明确阈值，再迁移至托管队列或 Redis/Celery。

## 9. AI Gateway

业务模块不直接调用模型 SDK，只调用内部接口：

```python
class HealthAI:
    async def recognize_meal(input: MealRecognitionInput) -> MealEstimate: ...
    async def draft_daily_advice(input: DailySummary) -> DailyAdvice: ...
    async def draft_weekly_plan(input: WeeklySummary) -> WeeklyPlan: ...
```

Gateway 负责 provider 路由、超时、重试、结构化输出验证、提示模板版本、成本/延迟指标、内容安全和脱敏审计。Provider 配置是部署配置，不写死在业务代码中。

## 10. 缓存与性能

MVP 不引入共享缓存。7 天看板使用带所有者条件的索引查询和轻量聚合。只有在观测显示数据库压力后才引入缓存，并确保缓存键包含用户范围、短 TTL、删除失效和不缓存高敏正文。

## 11. 部署拓扑

初期一台服务器运行：reverse proxy、web、api、worker、PostgreSQL 和对象存储。生产环境要求：

- 仅 443 暴露公网；数据库、对象存储管理端口和内部 API 不公开。
- 每个容器非 root、只读文件系统（可行处）、资源限制和健康检查。
- 数据卷和备份加密；备份复制到与主机隔离的位置。
- Secret 由部署环境注入，不进入镜像、Compose 文件或 Git。
- 测试/预发布/生产的数据库、Bucket、OIDC Client 和密钥完全隔离。

## 12. 可观测性

- 每个请求和任务生成 correlation ID。
- 日志采用结构化字段，禁止请求正文、Authorization、图片 URL、健康数据和 AI 完整输入输出进入普通日志。
- 指标：请求量、延迟、错误率、任务积压、AI 成功率/延迟/成本、对象校验失败、鉴权拒绝。
- 审计：登录安全事件、敏感数据读取、导出、删除、同意变化、共享变化（未来）和运维动作。
- 告警不得包含敏感内容；链接到受控调查界面。

## 13. 失败模式与降级

| 故障 | 用户体验 | 系统行为 |
| --- | --- | --- |
| AI 不可用 | 可手工记录，建议稍后生成 | 有限重试，不阻断核心 CRUD |
| 对象存储不可用 | 暂停照片上传，文本记录可用 | 不创建悬空业务引用 |
| Worker 停止 | 显示处理中 | 租约恢复、积压告警 |
| OIDC 不可用 | 已有短会话按策略继续；新登录暂停 | 不回退到自建弱认证 |
| 数据库不可用 | 只显示友好错误，不假装保存成功 | 熔断、健康检查、恢复流程 |

## 14. 扩展边界

- 报告：新增 `reports` 模块，通过 files 和 AI Gateway 集成。
- 设备：新增 `integrations` 模块，保存外部连接和来源，不修改核心记录所有权。
- 家庭共享：通过授权表和策略引擎增加资源级读取，不转移数据所有权。
- 订阅：新增 billing 模块，通过 entitlement 控制功能，不让计费状态污染健康数据表。
- 服务拆分：优先拆高吞吐或高隔离边界（文件处理、AI 任务），保持 API 契约和事件版本。

## 15. 关键待定项

在部署前必须确定：服务器数据地域、OIDC 服务、对象存储实现、AI Provider 及其数据保留/训练/地域政策、备份目的地、通知渠道。它们不会改变模块边界，但会改变部署和隐私告知。
