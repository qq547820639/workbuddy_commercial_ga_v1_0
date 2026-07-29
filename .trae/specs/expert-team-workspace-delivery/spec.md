# 专家团作为 AI 员工的看板与工作区交付 Spec

## Why

当前 WorkBuddy 的专家团系统在数据模型、调度、规划、执行、审批、Skill 库等代码层均已实现，但用户在主界面无法清晰感知"有哪些专家团存在、各自当前在做什么、如何进入对应 AI 员工的工作区查看详细进度"。团队详情仅以 modal 呈现、mission 全局浏览而非按团队分组、章程只读不可在线配置、跨团队协作未自动落地、子 agent 生命周期不透明。这些问题使用户无法理解专家团职责与交互模式，导致无法交付。本 spec 系统性梳理专家团作为 AI 员工的可见性、配置性与协作落地。

## What Changes

- 在主界面看板强化"专家团 = AI 员工"心智：每张卡片展示团队身份、主理人、当前 mission 摘要、活跃 WorkItem 数、待审批数、最近状态时间戳，并支持点击进入独立工作区页面。
- 新增"专家团工作区"独立页面（取代 modal）：按团队维度聚合 mission / WorkItem / AgentRun / 成员 / 章程 / Skill / 协作请求 / 记忆，提供实时进度感知（自动刷新）。
- 明确"主理人统一把控任务流转"的产品语义：主理人创建 WorkItem 任务清单并分配给子 agent，子 agent = 长期 AgentProfile + 一次性 AgentRun（执行完关闭并清理上下文，profile 复用）。在工作区显式呈现该生命周期。
- 落地跨专家团协作：当 dispatch 或主理人识别 `supporting_team_keys` 时，自动创建 `CollaborationRequest`，接收团队主理人可接受/拒绝，回传 Artifact 闭环。
- 章程与工作流支持运行时配置（草稿 → 审核 → 发布版本流），保留 YAML seed 作为平台默认，允许租户级覆盖。
- 团队级工具权限白名单：在 `TeamConstitutionVersion.config` 增加 `allowed_tools` 字段，AgentRun 授权时取 Skill.tools ∩ 团队 allowed_tools。
- 扩充专家团类型：在 `config/teams/` 增加至少 2 个新职责团队（如 hr_people、finance_ops），覆盖更多业务类型。
- Skill 库在工作区内可见：展示团队可用 Skill（平台 + 用户上传），支持从工作区发起上传 / 测试 / 发布。
- 看板与工作区支持自动刷新（轮询），并标注数据时间戳，确保用户可感知实时进度。
- **BREAKING**：`TeamConstitutionVersion.config` JSON schema 新增 `allowed_tools` 字段；旧 YAML 缺省该字段时按"不限制"处理（向后兼容）。

## Impact

- Affected specs: 专家团任务闭环、Skill 与 Tool 治理、Gate Evidence、Production Pilot 管理、Commercial GA 运营控制台
- Affected code:
  - `src/workbuddy/db/models.py`：可能新增 `TeamToolAllowlist` 或在 `TeamConstitutionVersion.config` 扩展字段；`CollaborationRequest` 状态机补全
  - `src/workbuddy/services/dispatch.py`：自动创建 `CollaborationRequest`
  - `src/workbuddy/services/business.py`：协作请求接受/拒绝/回传 Artifact 流程
  - `src/workbuddy/services/skills.py` / `tools.py`：团队级工具权限交集校验
  - `src/workbuddy/services/seed.py`：新团队 YAML 加载
  - `src/workbuddy/api/main.py` / `commercial_routes.py` / 新增 `team_routes.py`：工作区页面所需 API
  - `src/workbuddy/web/index.html`：看板卡片强化 + 新增工作区页面 + 自动刷新
  - `config/teams/`：新增团队 YAML
  - `tests/`：协作请求、团队工具权限、工作区 API、新团队 seed 测试

## ADDED Requirements

### Requirement: 专家团 AI 员工看板卡片

系统 SHALL 在主界面看板为每个 active 专家团展示一张"AI 员工卡片"，至少包含：团队名称、team_key、主理人姓名、charter 一句话使命、当前进行中 mission 数、活跃 WorkItem 数、待审批数、最近状态变更时间戳。卡片 SHALL 支持点击进入该团队的独立工作区页面。

#### Scenario: 看板展示全部 active 团队
- **WHEN** 用户进入主界面看板
- **THEN** 看板显示所有 `active=True` 的 `TeamDefinition` 对应的卡片
- **AND** 每张卡片显示主理人姓名（来自 `AgentProfile.is_lead=True`）
- **AND** 卡片显示当前进行中 mission 数（`Mission.status` 属于 ROUTED/LEAD_TRIAGE/PLANNING/READY/EXECUTING/LEAD_REVIEW/APPROVAL_REQUIRED/APPROVED/ACTION_EXECUTING/VERIFYING）
- **AND** 卡片显示活跃 WorkItem 数（`WorkItem.status` 属于 ASSIGNED/RUNNING/SUBMITTED）
- **AND** 卡片显示待审批数（`ApprovalRequest.status=PENDING` 且 mission 属于该团队）

#### Scenario: 点击卡片进入工作区
- **WHEN** 用户点击某张团队卡片
- **THEN** 路由跳转到该团队的独立工作区页面 `/team/{team_key}`
- **AND** 工作区页面以该团队为维度聚合所有数据

#### Scenario: 卡片自动刷新
- **WHEN** 用户停留在看板页面
- **THEN** 卡片数据每 30 秒自动轮询刷新
- **AND** 卡片显示"最后更新时间"时间戳

### Requirement: 专家团独立工作区页面

系统 SHALL 为每个专家团提供独立的工作区页面 `/team/{team_key}`，按团队维度聚合：身份与章程、长期成员（AgentProfile）、当前与历史 mission、活跃 WorkItem 与 AgentRun、可用 Skill、跨团队协作请求、团队记忆。工作区 SHALL 支持自动刷新。

#### Scenario: 工作区展示团队身份与章程
- **WHEN** 用户进入 `/team/{team_key}`
- **THEN** 页面展示团队名称、使命、`in_scope`、`out_of_scope`、主理人、成员列表
- **AND** 展示当前生效的 `TeamConstitutionVersion`（含版本号、状态、`allowed_tools`）

#### Scenario: 工作区按团队维度展示 mission
- **WHEN** 用户进入工作区
- **THEN** mission 列表仅展示 `primary_team_id = 当前团队` 的 mission
- **AND** 支持"进行中 / 全部"过滤
- **AND** 每个 mission 显示状态、目标、主理人、WorkItem 进度（已完成/总数）

#### Scenario: 工作区展示子 agent 生命周期
- **WHEN** 用户进入某 mission 详情
- **THEN** 页面显式区分"长期成员（AgentProfile）"与"执行实例（AgentRun）"
- **AND** 每个 WorkItem 显示分配的 AgentProfile、当前 AgentRun 状态、context_cleared 标记
- **AND** 关闭的 AgentRun 显示 `close_reason`，并标注"上下文已清理，profile 复用"

#### Scenario: 工作区展示可用 Skill
- **WHEN** 用户进入工作区 Skill 区
- **THEN** 展示该团队 `allowed_roles` 可用的所有 SkillRelease（平台 + 用户上传）
- **AND** 支持"从工作区发起 Skill 上传 / 测试 / 发布"

#### Scenario: 工作区自动刷新
- **WHEN** 用户停留在工作区页面
- **THEN** 进行中 mission 与活跃 AgentRun 数据每 15 秒自动轮询刷新
- **AND** 显示"最后更新时间"

### Requirement: 主理人统一把控任务流转

系统 SHALL 在工作区与 mission 详情中明确呈现"主理人统一把控任务流转"的语义：主理人创建 WorkItem 任务清单、按角色分配给长期 AgentProfile、每个 WorkItem 启动一次性 AgentRun 执行、AgentRun 关闭后清理上下文但 AgentProfile 持续复用。

#### Scenario: 主理人创建任务清单并分配
- **WHEN** 主理人对 ROUTED 状态 mission 执行"生成清单"
- **THEN** 系统调用 `planner.build_plan` 生成 WorkItem 列表
- **AND** 每个 WorkItem 绑定 `assigned_agent_profile_id`（按 role 匹配的长期 AgentProfile）
- **AND** 每个 WorkItem 绑定 `skill_release_id`（冻结版本 Skill）
- **AND** 工作区显示"主理人 → 子 agent（角色）→ 执行实例"的层级关系

#### Scenario: 子 agent 执行实例关闭后复用 profile
- **WHEN** 某 WorkItem 的 AgentRun 进入 CLOSED 状态
- **THEN** `context_cleared=True`，临时上下文清理
- **AND** AgentProfile 保持 active，可被后续 WorkItem 再次分配
- **AND** 工作区显示"该成员当前空闲，可接受新任务"

#### Scenario: 主理人显式重试失败 WorkItem
- **WHEN** WorkItem 因 AgentRun FAILED 进入 BLOCKED
- **THEN** 主理人需显式创建新 AgentRun 重试
- **AND** 系统 NOT 自动重试（保持现有语义）

### Requirement: 跨专家团协作自动落地

系统 SHALL 在 dispatch 或主理人规划阶段识别 `supporting_team_keys` 时，自动创建 `CollaborationRequest`；接收团队主理人可接受/拒绝；接受后由接收团队执行子任务并回传 Artifact，发起团队消费 Artifact 继续流转。

#### Scenario: dispatch 自动创建协作请求
- **WHEN** dispatch 返回 `supporting_team_keys` 非空
- **THEN** `confirm_dispatch` 时系统自动为每个 supporting team 创建 `CollaborationRequest`（status=PENDING）
- **AND** 协作请求关联发起团队、接收团队、objective、expected_artifact
- **AND** 接收团队工作区"协作请求"区显示该请求

#### Scenario: 接收团队接受协作
- **WHEN** 接收团队主理人点击"接受"
- **THEN** `CollaborationRequest.status = ACCEPTED`
- **AND** 接收团队可创建对应子 mission 或 WorkItem 执行
- **AND** 发起团队工作区显示"协作已接受，等待回传"

#### Scenario: 回传 Artifact 闭环
- **WHEN** 接收团队完成子任务并提交 Artifact
- **THEN** 发起团队 mission 可消费该 Artifact 作为后续 WorkItem 输入
- **AND** `CollaborationRequest.status = COMPLETED`
- **AND** 发起团队工作区显示"协作已完成，Artifact 已回传"

#### Scenario: 拒绝协作
- **WHEN** 接收团队主理人点击"拒绝"并填写理由
- **THEN** `CollaborationRequest.status = DECLINED`
- **AND** 发起团队工作区显示"协作被拒绝：{理由}"
- **AND** 主理人可重新规划或请求其他团队

### Requirement: 团队级工具权限白名单

系统 SHALL 在 `TeamConstitutionVersion.config` 引入 `allowed_tools` 字段（字符串列表），AgentRun 授权时取 `SkillRelease.config.tools` ∩ `团队 allowed_tools`；缺省 `allowed_tools` 时按"不限制"处理（向后兼容）。

#### Scenario: 团队工具白名单收紧
- **GIVEN** 团队章程 `allowed_tools: ["mail.read", "mail.search"]`
- **AND** Skill 声明 `tools: ["mail.read", "mail.send"]`
- **WHEN** AgentRun 启动并调用 `create_run_grants`
- **THEN** 仅授予 `mail.read`，不授予 `mail.send`
- **AND** AgentRun 调用 `mail.send` 时被 `invoke_tool` 拒绝

#### Scenario: 缺省 allowed_tools 向后兼容
- **GIVEN** 团队章程未定义 `allowed_tools`
- **WHEN** AgentRun 启动
- **THEN** 按 Skill 声明的完整 tools 列表授权（保持现有行为）

### Requirement: 章程与工作流运行时配置

系统 SHALL 支持租户级运行时配置专家团章程与工作流：草稿 → 审核 → 发布版本流，保留平台 YAML seed 作为默认，允许租户级覆盖。在途 Mission 绑定的 `constitution_version_id` 不受新版本影响。

#### Scenario: 创建章程草稿
- **WHEN** 租户管理员在工作区"章程"区编辑并保存
- **THEN** 系统创建新 `TeamConstitutionVersion`（status=draft，config=新内容）
- **AND** 旧 published 版本保持不变

#### Scenario: 审核与发布
- **WHEN** 管理员对 draft 版本执行"提交审核"→"审核通过"→"发布"
- **THEN** 版本状态流转 `draft → reviewing → approved → published`
- **AND** 新 published 版本成为该团队当前生效章程
- **AND** 已存在的在途 Mission 仍绑定旧版本（不变更）

#### Scenario: 在途 mission 不受新版本影响
- **GIVEN** Mission A 绑定 constitution v1
- **WHEN** 管理员发布 constitution v2
- **THEN** Mission A 仍绑定 v1
- **AND** 新建 Mission 使用 v2

### Requirement: 扩充专家团类型

系统 SHALL 在 `config/teams/` 增加至少 2 个新职责团队，覆盖更多业务类型，每个团队包含完整 charter / lead_role / in_scope / out_of_scope / routing_rules / default_workflows / quality_gates / memory_policy / metrics，且引用的 Skill 在 `config/skills/` 存在。

#### Scenario: 新团队被 seed 加载
- **WHEN** 执行 `seed_all`
- **THEN** 新团队 YAML 被加载为 `TeamDefinition` + `TeamConstitutionVersion`（status=published）
- **AND** 引用的 workflow 创建为 `WorkflowVersion`
- **AND** 引用的 role 创建为 `AgentProfile`（含主理人）
- **AND** 引用的 Skill 通过 `ensure_skill` 加载

#### Scenario: 新团队可被 dispatch 识别
- **GIVEN** 新团队的 `routing_rules.positive_signals` 配置
- **WHEN** 邮件文本命中新团队 positive_signals
- **THEN** dispatch 评分阶段将新团队纳入候选
- **AND** LLM 分类可能返回新团队作为 primary_team_key

## MODIFIED Requirements

### Requirement: 专家团任务闭环

原有专家团任务闭环已实现调度、主理人、WorkItem、AgentRun、复核、审批、外部操作。本变更 SHALL 在此基础上：看板与工作区按团队维度呈现任务流转；子 agent 生命周期（长期 profile + 一次性 run）显式可见；跨团队协作请求自动落地并回传 Artifact 闭环。

### Requirement: Skill 与 Tool 治理

原有 Skill 与 Tool 治理已实现版本、测试、权限、撤权和审计。本变更 SHALL 在此基础上：团队章程引入 `allowed_tools` 白名单；AgentRun 授权取 Skill.tools ∩ 团队 allowed_tools；工作区可发起 Skill 上传 / 测试 / 发布；缺省 allowed_tools 向后兼容。

### Requirement: 看板与主界面

原有主界面已实现 11 个功能区与团队卡片 modal。本变更 SHALL 在此基础上：团队卡片强化为 AI 员工卡片（含状态指标 + 时间戳）；新增独立工作区页面（取代 modal）；看板与工作区支持自动刷新；mission 按团队维度分组浏览。

## REMOVED Requirements

无移除项。本变更保持现有数据模型与状态机不变，仅扩展与呈现。
