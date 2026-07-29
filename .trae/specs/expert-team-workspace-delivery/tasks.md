# Tasks

## 阶段 1：数据模型与状态机扩展

- [x] Task 1: 扩展 `TeamConstitutionVersion.config` 与 `CollaborationRequest` 状态机
  - [x] SubTask 1.1: 在 `TeamConstitutionVersion.config` JSON schema 中新增 `allowed_tools` 字段（字符串列表），更新 seed YAML 加载逻辑兼容缺省情况
  - [x] SubTask 1.2: 在 `src/workbuddy/domain/state_machine.py` 新增 `CollaborationRequestStatus` 状态机：`PENDING → ACCEPTED → IN_PROGRESS → COMPLETED` / `PENDING → DECLINED` / `ACCEPTED → FAILED`
  - [x] SubTask 1.3: 新增 Alembic 迁移 `0020_team_tool_allowlist_and_collab_state.py`，记录 schema 变更（如有列变更）

## 阶段 2：跨专家团协作落地

- [x] Task 2: 落地 `CollaborationRequest` 自动创建与闭环
  - [x] SubTask 2.1: 修改 `src/workbuddy/services/business.py`（confirm_dispatch 流程），在确认转交时为 `supporting_team_keys` 每个 team 自动创建 `CollaborationRequest`（PENDING）
  - [x] SubTask 2.2: 在 `src/workbuddy/services/business.py` 新增 `accept_collaboration` / `decline_collaboration` / `complete_collaboration_with_artifact` 方法，校验状态机
  - [x] SubTask 2.3: 实现 Artifact 回传机制：接收团队提交 Artifact 后，发起团队 mission 后续 WorkItem 可消费该 Artifact 作为输入

## 阶段 3：团队级工具权限白名单

- [x] Task 3: 实现团队级工具权限交集校验
  - [x] SubTask 3.1: 修改 `src/workbuddy/services/tools.py::create_run_grants`，读取 `TeamConstitutionVersion.config.allowed_tools`，与 `SkillRelease.config.tools` 取交集授权
  - [x] SubTask 3.2: 缺省 `allowed_tools` 时按完整 Skill.tools 授权（向后兼容）
  - [x] SubTask 3.3: 在 `tests/test_tools_planning_outbox.py` 新增测试：白名单收紧场景 + 缺省兼容场景

## 阶段 4：扩充专家团类型

- [x] Task 4: 新增至少 2 个新职责团队 YAML 与对应 Skill
  - [x] SubTask 4.1: 在 `config/teams/` 新增 `hr_people.yaml`（HR 与人事专家团：含 hr_lead 主理人 + 招聘/员工关系/薪酬子角色，2 个工作流）
  - [x] SubTask 4.2: 在 `config/teams/` 新增 `finance_ops.yaml`（财务与运营专家团：含 finance_lead 主理人 + 应收/应付/报表子角色，2 个工作流）
  - [x] SubTask 4.3: 在 `config/skills/` 新增新团队引用的 Skill YAML（如 hr-candidate-screening、finance-invoice-reconciliation 等）
  - [x] SubTask 4.4: 验证 `seed_all` 加载新团队、workflow、AgentProfile、SkillRelease 无错误
  - [x] SubTask 4.5: 在 `tests/` 新增测试验证新团队被 seed 加载、可被 dispatch 识别

## 阶段 5：章程与工作流运行时配置

- [x] Task 5: 实现章程草稿 → 审核 → 发布版本流
  - [x] SubTask 5.1: 在 `src/workbuddy/services/business.py` 新增 `create_constitution_draft` / `submit_for_review` / `approve_constitution` / `publish_constitution` 方法
  - [x] SubTask 5.2: 状态流转 `draft → reviewing → approved → published`，新 published 版本成为当前生效，在途 Mission 不变更
  - [x] SubTask 5.3: 在 `tests/test_security_and_governance.py` 新增测试：在途 mission 不受新版本影响

## 阶段 6：工作区与看板 API

- [x] Task 6: 新增团队工作区所需 API 端点
  - [x] SubTask 6.1: 新建 `src/workbuddy/api/team_routes.py`，提供：`GET /v1/teams/{team_key}/dashboard`（卡片聚合数据）、`GET /v1/teams/{team_key}/workspace`（工作区完整聚合：章程+成员+mission+WorkItem+AgentRun+Skill+协作请求+记忆）
  - [x] SubTask 6.2: 在 `team_routes.py` 提供：`GET /v1/teams/{team_key}/missions`（按团队过滤 mission，支持进行中/全部）、`GET /v1/teams/{team_key}/collaborations`（团队参与的协作请求）
  - [x] SubTask 6.3: 在 `team_routes.py` 提供：`POST /v1/teams/{team_key}/collaborations/{id}/accept`、`POST .../decline`、`POST .../complete` 端点
  - [x] SubTask 6.4: 在 `team_routes.py` 提供：`POST /v1/teams/{team_key}/constitution/draft`、`POST .../submit-review`、`POST .../approve`、`POST .../publish` 端点
  - [x] SubTask 6.5: 在 `src/workbuddy/api/main.py` 注册 `team_routes` router，更新 OpenAPI 生成

## 阶段 7：前端看板与工作区

- [x] Task 7: 强化看板 AI 员工卡片 + 新增工作区页面
  - [x] SubTask 7.1: 修改 `src/workbuddy/web/index.html` 看板卡片：增加主理人、进行中 mission 数、活跃 WorkItem 数、待审批数、最后更新时间戳；点击跳转 `/team/{team_key}`
  - [x] SubTask 7.2: 新增工作区页面（单页路由 `/team/{team_key}`）：身份与章程区、成员区（显式区分长期 AgentProfile 与一次性 AgentRun）、mission 列表区（按团队过滤）、Skill 区、协作请求区、记忆区
  - [x] SubTask 7.3: 在 mission 详情显式呈现"主理人 → 子 agent（角色）→ 执行实例"层级，标注 context_cleared 与 close_reason
  - [x] SubTask 7.4: 看板每 30 秒自动轮询刷新，工作区每 15 秒自动轮询刷新，显示"最后更新时间"
  - [x] SubTask 7.5: 工作区章程区支持编辑（创建草稿）、提交审核、审核通过、发布操作
  - [x] SubTask 7.6: 工作区协作请求区支持接受/拒绝/完成回传操作

## 阶段 8：测试与验证

- [x] Task 8: 端到端测试与验证
  - [x] SubTask 8.1: 在 `tests/` 新增 `test_expert_team_workspace.py`：覆盖看板卡片 API、工作区聚合 API、按团队 mission 过滤、子 agent 生命周期展示
  - [x] SubTask 8.2: 确认 `test_collaboration_flow.py`（Task 2 已覆盖）：dispatch 自动创建协作请求 → 接受 → 执行 → 回传 Artifact → COMPLETED 闭环；拒绝路径
  - [x] SubTask 8.3: 确认团队工具权限测试（Task 3 已覆盖）：白名单收紧 + 缺省兼容
  - [x] SubTask 8.4: 确认章程版本隔离测试（Task 5 已覆盖）：在途 mission 不受新版本影响
  - [x] SubTask 8.5: 扩展 `test_alpha_flow.py` 验证多团队场景（含 supporting team 自动协作）
  - [x] SubTask 8.6: 运行 `./scripts/verify.sh` 确保全量验证通过（76 测试 + 12 步全绿）

# Task Dependencies

- Task 2 依赖 Task 1（状态机先行）
- Task 3 依赖 Task 1（allowed_tools 字段先行）
- Task 6 依赖 Task 2、Task 3、Task 5（API 需要业务方法就绪）
- Task 7 依赖 Task 6（前端调用 API）
- Task 8 依赖 Task 2–Task 7 全部完成
- Task 4 可与 Task 2、Task 3 并行（独立 YAML 与 seed 工作）
