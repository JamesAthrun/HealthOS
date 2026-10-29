# HealthOS 开发路线与交付计划

## 总体策略

先建立可验证的安全和数据基础，再添加记录，再闭合 AI 规划。每一阶段都有退出条件；未达到条件不进入家庭真实数据试用。

## 阶段 0：工程与安全基础

### 交付

- 初始化 Next.js、FastAPI、测试和统一开发命令。
- PostgreSQL + Alembic；建立迁移/运行时独立角色。
- OIDC 登录、内部用户映射、授权中间件和 RLS 基础。
- 私有对象存储上传、验证、短期访问 URL。
- 脱敏日志、请求 ID、审计事件和基础指标。
- 数据库/对象备份脚本、恢复手册和一次恢复演练。
- CI：格式、类型、测试、Secret/依赖/镜像扫描。

### 验收

- 两个测试用户无法通过任意资源 ID 互访。
- 数据库和对象存储端口不暴露公网。
- 日志样本中无 Token、请求正文或健康数据。
- 备份在隔离环境恢复，应用烟雾测试通过。

## 阶段 1：健康记录 MVP

### 交付

- 首次使用、健康档案和目标。
- 饮食手工记录、照片上传、AI 识别、编辑确认。
- 运动和睡眠 CRUD。
- 今日概览与 7 天趋势。
- 记录导出/删除的最小流程。
- 移动端核心流程与无障碍检查。

### 验收

- 手机上能完成全部记录，AI 失败不阻断手工录入。
- 所有正式饮食数据都可追溯到用户确认。
- 时区、跨午夜睡眠、重复提交和并发编辑测试通过。
- 用户可查询、修改、删除并导出自己的数据。

## 阶段 2：AI 规划闭环

### 交付

- 数据摘要服务和证据引用。
- 次日建议、每周计划草稿、编辑确认和执行反馈。
- Provider Adapter、模板/Schema 版本和成本指标。
- AI 同意、撤回、保留和安全过滤。
- 合成评估集与持续回归。

### 验收

- 建议只引用当前用户允许范围内的真实记录。
- 记录不足时说明局限，不虚构输入。
- 危险/医疗用例被确定性拦截。
- Provider 不可用时核心记录功能正常。

## 阶段 3：家庭试运行与稳定化

此阶段不是“家庭共享”；仍是每人独立私密账号。

### 交付

- 邀请制试用、反馈和支持流程。
- 性能、错误率、AI 成本与任务积压看板。
- 数据删除、恢复、事件响应演练。
- 产品说明、隐私说明和非医疗边界定稿。

### 验收

- 连续 4 周达到 PRD 可靠性和使用指标。
- 无未解决高危安全问题。
- 所有试用者理解 AI 局限和数据处理方式。

## 阶段 4：扩展（按证据排序）

候选：体检报告、设备集成、主动授权的家庭共享、菜谱/购物清单、专家协作、订阅。每项都需要单独 PRD、威胁模型和退出方案，不因数据模型预留而自动进入开发。

## 建议的首批 Issue

1. `chore: initialize frontend and backend toolchains`
2. `infra: provision local postgres and private object storage`
3. `feat(auth): integrate OIDC and internal user mapping`
4. `security: add user-scoped repository pattern and RLS tests`
5. `feat(files): implement validated private image upload`
6. `feat(profile): implement profile and goals`
7. `feat(records): implement meal, exercise and sleep CRUD`
8. `feat(ai): add provider interface and meal recognition schema`
9. `feat(dashboard): add daily and seven-day aggregates`
10. `privacy: implement consent, export and deletion workflows`
11. `feat(planning): add daily advice and weekly plans`
12. `ops: implement encrypted backup and restore drill`

## Definition of Done

一项功能只有在以下条件满足时完成：

- 有明确验收标准和产品边界。
- 前后端验证、授权和失败路径已实现。
- 单元、集成和必要的端到端测试通过。
- 日志、指标和审计不泄露敏感数据。
- 数据库迁移支持升级，并有明确回滚/前滚策略。
- API 和用户文档已更新。
- 对新增第三方或数据流完成隐私与威胁审查。

## 下一步决策

开始阶段 0 前，由项目所有者确认：

1. 生产服务器所在地（中国大陆/香港/新加坡/美国等）。
2. 首选 OIDC 身份服务。
3. 首选 AI Provider 及数据处理条件。
4. 是否先只在局域网/受控 VPN 内试用。
5. 备份目标和可接受的恢复目标。
