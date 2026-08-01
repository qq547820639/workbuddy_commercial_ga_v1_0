# 飞书原生 WorkBuddy 核心业务 Spec

## Why

WorkBuddy 的核心价值是**邮件驱动的 AI 员工协作平台**：邮件到达 → dispatch 智能派单 → 创建任务(Mission) → 主理人规划工作项(WorkItem) → 智能体执行(AgentRun) → 审批 → 外部操作交付。当前实现依赖本地 FastAPI 服务器 + Gmail/Outlook 连接器 + PostgreSQL，需要公网 IP 暴露 webhook。

之前的 `feishu-app-native` spec 退化成了浅层"邮件→IM通知"，丢失了任务编排、智能体协作、审批管控等核心业务。本 spec 把 WorkBuddy 的**全量核心业务**用飞书全家桶 + 妙搭重新实现，让业务用户在飞书工作台完成从邮件到交付的完整闭环。

## What Changes

### 核心闭环映射

| WorkBuddy 原始模块 | 当前实现 | 飞书原生替代 | 飞书能力 |
|---|---|---|---|
| 邮件接入 | Gmail/Outlook + webhook（需公网IP） | 飞书邮箱 OAuth + 事件订阅 | lark-mail |
| 邮件事件触发 | Google Pub/Sub webhook 回调 | 飞书事件订阅 → 妙搭云函数回调（无需公网IP） | 飞书事件订阅 |
| dispatch 派单 | Python + LLM 分类 | 妙搭云函数 + LLM API | 妙搭云函数 |
| Mission/WorkItem | SQLAlchemy 模型 | 飞书任务 + 多维表格 | lark-task + lark-base |
| AgentRun 执行 | Python + ModelGateway(LLM) | 妙搭云函数 + LLM API | 妙搭云函数 |
| 审批管控 | ApprovalRequest 状态机 | 飞书审批流 | lark-approval |
| 外部操作 | ExternalOperation（发邮件等） | 飞书邮箱发信 / IM 通知 | lark-mail + lark-im |
| 数据存储 | PostgreSQL | 飞书多维表格 | lark-base |
| 章程治理 | TeamConstitutionVersion YAML | 飞书文档 + 版本历史 | lark-doc |
| 看板与工作区 | FastAPI Web UI | 妙搭 HTML 控制台 | 妙搭应用 |
| 调度 | scheduler_tick 定时 | 飞书事件 + 妙搭自动触发 | lark-event |
| LLM 调用 | ModelGateway（OpenAI/Anthropic） | 妙搭云函数直连 LLM API | 妙搭云函数 |

### 分阶段交付

- **阶段 A（数据层）**：多维表格映射核心域模型（团队/智能体/任务/工作项/执行/审批/产物/证据/协作请求）
- **阶段 B（邮件→dispatch）**：飞书邮箱 OAuth 接入 + 事件订阅 → 妙搭云函数 → LLM dispatch 派单 → 创建 Mission
- **阶段 C（任务执行）**：主理人规划 WorkItem → AgentRun 调 LLM 执行 → 产出 Artifact + Evidence
- **阶段 D（审批交付）**：高风险操作触发飞书审批 → 审批通过执行外部操作 → 闭环通知
- **阶段 E（看板工作区）**：妙搭控制台呈现专家团看板 + 独立工作区 + 自动刷新

### 关键架构决策

1. **飞书事件订阅替代轮询**：妙搭云函数提供回调 URL，飞书邮箱收到新邮件时实时推送事件，无需 30 分钟轮询
2. **飞书 OAuth 替代 IMAP 密码**：自建应用申请 `mail:user_mailbox:*` scope，用户点同意即授权
3. **妙搭云函数直连 LLM**：云函数内调用 OpenAI/Anthropic API，密钥存妙搭环境变量；ModelGateway 的预算管控逻辑迁移到云函数
4. **飞书任务映射 Mission/WorkItem**：Mission = 飞书任务清单，WorkItem = 子任务，状态变更双向同步
5. **飞书审批映射 ApprovalRequest**：高风险操作自动创建飞书审批实例，审批结果回调更新 Mission 状态
6. **多维表格替代数据库**：核心域模型映射为多维表格表，妙搭数据库做补充（日志/配置）

## Impact

- Affected specs:
  - `expert-team-workspace-delivery`：核心业务需求来源，本 spec 是其在飞书原生平台的实现
  - `feishu-native-workbuddy`（阶段1 MVP）：邮箱→IM 通知链路被本 spec 阶段 B 替代
  - `feishu-base-data-layer`（阶段2）：多维表格数据层被本 spec 阶段 A 扩展（从仅邮件归档扩展到全核心域）
  - `feishu-app-native`（阶段3 原方案）：妙搭应用方向被本 spec 继承并修正（从浅层邮件通知修正为核心业务闭环）
  - `refactor-p1-abstraction-transactions`：Gmail/Outlook 连接器 ABC 化将被废弃
- Affected code:
  - 新增 `feishu-app/` 妙搭应用代码（云函数 + 控制台 + 共享库）
  - `feishu/` Python 脚本逐步废弃（阶段 E 完成后删除）
  - `src/workbuddy/` 现有代码保持不动（飞书原生方案独立运行，不修改现有系统）

## ADDED Requirements

### Requirement: 飞书邮箱 OAuth 接入

系统 SHALL 通过飞书自建应用 OAuth 授权访问用户邮箱，无需 IMAP 密码或公网 IP。

#### Scenario: 用户授权邮箱
- **GIVEN** 飞书自建应用已申请 `mail:user_mailbox:readonly` scope
- **WHEN** 用户在飞书工作台点 WorkBuddy 图标
- **THEN** 跳转 OAuth 授权页，用户点"同意"
- **AND** 系统获得 user_access_token，可读取用户邮箱邮件
- **AND** 整个过程不要求用户输入密码或配置 IMAP

### Requirement: 飞书事件订阅实时邮件触发

系统 SHALL 通过飞书事件订阅接收新邮件事件，回调到妙搭云函数，无需轮询或公网 IP。

#### Scenario: 新邮件实时触发
- **GIVEN** 飞书自建应用已配置事件订阅，回调 URL 指向妙搭云函数
- **WHEN** 用户飞书邮箱收到新邮件
- **THEN** 飞书在秒级内推送邮件事件到妙搭云函数
- **AND** 云函数立即触发 dispatch 流程，无需等待轮询周期
- **AND** 整个链路纯出站 + 妙搭回调，不需要用户暴露公网 IP

### Requirement: dispatch 智能派单

系统 SHALL 在收到新邮件后，调用 LLM 对邮件进行分类派单，匹配专家团并创建 Mission。

#### Scenario: 邮件分类派单
- **GIVEN** 邮件事件已到达妙搭云函数
- **WHEN** 云函数调用 LLM（传入邮件主题+正文+专家团 routing_rules）
- **THEN** LLM 返回 business_type / primary_team_key / risk_level / confidence
- **AND** 系统创建 Mission（状态=ROUTED，绑定团队、来源邮件、风险等级）
- **AND** 在多维表格"任务"表创建对应记录
- **AND** 在飞书任务创建对应任务清单
- **AND** 高风险邮件（risk_level=high/critical）自动触发审批流

#### Scenario: dispatch 识别跨团队协作
- **WHEN** LLM 返回 supporting_team_keys 非空
- **THEN** 系统为每个 supporting team 创建 CollaborationRequest（状态=PENDING）
- **AND** 接收团队工作区显示协作请求

### Requirement: 主理人规划工作项

系统 SHALL 支持主理人对 ROUTED 状态 Mission 生成 WorkItem 任务清单，按角色分配给长期 AgentProfile。

#### Scenario: 主理人生成清单
- **GIVEN** Mission 状态为 ROUTED
- **WHEN** 主理人在工作区点"生成清单"
- **THEN** 云函数调用 LLM（planner）根据团队 workflow 生成 WorkItem 列表
- **AND** 每个 WorkItem 绑定 assigned_agent_profile_id（按 role 匹配）
- **AND** 每个 WorkItem 绑定 skill_release_id（冻结版本 Skill）
- **AND** 在多维表格"工作项"表创建记录
- **AND** 在飞书任务创建子任务

### Requirement: 智能体执行 AgentRun

系统 SHALL 支持启动 AgentRun 调用 LLM 执行 WorkItem，产出 Artifact 和 Evidence。

#### Scenario: 启动 AgentRun
- **GIVEN** WorkItem 状态为 ASSIGNED
- **WHEN** 主理人启动执行
- **THEN** 创建 AgentRun（状态=RUNNING）
- **AND** 云函数调用 LLM（传入 mission/work_item/agent_profile/skill/source 上下文）
- **AND** LLM 返回 artifact + evidence
- **AND** AgentRun 状态=SUBMITTED，WorkItem 状态=SUBMITTED
- **AND** 在多维表格记录执行结果

#### Scenario: 产出 Artifact 和 Evidence
- **WHEN** AgentRun 完成
- **THEN** 系统创建 Artifact 记录（含内容哈希）
- **AND** 系统创建 Evidence 记录（含验证状态）
- **AND** 主理人可复核并决定是否需要审批

### Requirement: 飞书审批集成

系统 SHALL 对高风险操作（退款/补偿/法律承诺/外部发信）自动创建飞书审批实例，审批结果回调更新 Mission 状态。

#### Scenario: 高风险操作触发审批
- **GIVEN** WorkItem 的 approval_triggers 包含触发的操作类型
- **WHEN** 主理人提交需审批的操作
- **THEN** 系统调用飞书审批 API 创建审批实例
- **AND** 审批人收到飞书审批通知
- **AND** Mission 状态=APPROVAL_REQUIRED

#### Scenario: 审批通过执行外部操作
- **WHEN** 审批人批准
- **THEN** 飞书审批回调通知妙搭云函数
- **AND** Mission 状态=APPROVED
- **AND** 系统执行外部操作（发邮件/IM通知）
- **AND** 记录 ExternalOperation 审计日志

#### Scenario: 审批拒绝
- **WHEN** 审批人拒绝
- **THEN** Mission 状态=BLOCKED
- **AND** 主理人收到拒绝通知，可重新规划

### Requirement: 专家团看板

系统 SHALL 在妙搭控制台展示专家团 AI 员工看板，每张卡片显示团队身份、主理人、当前 Mission 摘要、活跃 WorkItem 数、待审批数、最近状态时间戳。

#### Scenario: 看板展示全部团队
- **WHEN** 用户进入控制台首页
- **THEN** 显示所有 active 专家团的卡片
- **AND** 每张卡片显示团队名/主理人/进行中任务数/待审批数
- **AND** 卡片支持点击进入团队工作区
- **AND** 数据每 30 秒自动刷新

### Requirement: 专家团独立工作区

系统 SHALL 为每个专家团提供独立工作区页面，按团队维度聚合 Mission/WorkItem/AgentRun/成员/章程/Skill/协作请求。

#### Scenario: 工作区展示任务流转
- **WHEN** 用户进入团队工作区
- **THEN** 显示该团队的 Mission 列表（进行中/全部过滤）
- **AND** 每个 Mission 显示状态/目标/主理人/WorkItem 进度
- **AND** 可展开查看 WorkItem 和 AgentRun 详情
- **AND** 显式区分长期成员（AgentProfile）与执行实例（AgentRun）

#### Scenario: 工作区展示协作请求
- **WHEN** 用户进入工作区"协作"区
- **THEN** 显示收到的 CollaborationRequest 列表
- **AND** 主理人可接受/拒绝协作
- **AND** 接受后可创建子任务执行

### Requirement: 多维表格核心域数据层

系统 SHALL 在飞书多维表格建立 WorkBuddy 核心域数据层，映射全部核心模型。

#### Scenario: 核心域表结构
- **GIVEN** 多维表格 Base 已初始化
- **THEN** 包含以下表：邮件归档/团队/智能体/任务/工作项/执行记录/审批请求/产物/证据/协作请求/运行日志/配置
- **AND** 每张表的字段映射对应 ORM 模型的关键属性
- **AND** 支持按字段过滤查询（如按 team_key 查任务）

### Requirement: 章程与工作流配置

系统 SHALL 支持租户级运行时配置专家团章程与工作流，保留 YAML seed 作为默认。

#### Scenario: 章程版本管理
- **GIVEN** 团队已有 published 章程版本
- **WHEN** 管理员编辑章程并保存
- **THEN** 创建新 draft 版本
- **AND** 旧 published 版本保持不变
- **AND** 在途 Mission 不受影响

## MODIFIED Requirements

### Requirement: 邮件接入

原有 Gmail/Outlook 连接器（需公网 IP + webhook）被飞书邮箱 OAuth + 事件订阅替代。用户无需配置 IMAP 或暴露公网 IP。

### Requirement: 任务系统

原有 SQLAlchemy Mission/WorkItem/AgentRun 模型扩展为多维表格记录 + 飞书任务双向同步。状态变更在两侧保持一致。

### Requirement: 审批流

原有 ApprovalRequest 状态机扩展为飞书审批集成。高风险操作自动创建飞书审批实例，审批结果实时回调。

## REMOVED Requirements

### Requirement: Gmail/Outlook 连接器
**Reason**: 飞书邮箱 OAuth 替代外部邮件服务
**Migration**: 现有 Gmail/Outlook 连接器代码保留不动（不删除），飞书原生方案独立运行

### Requirement: 本地 FastAPI 服务器
**Reason**: 妙搭云函数 + 飞书事件订阅替代本地服务器
**Migration**: `src/workbuddy/api/` 代码保留不动，飞书原生方案独立运行

## 假设与约束

- **部署形态**：妙搭全栈应用，云函数 + 数据库 + HTML 控制台全部在妙搭云端
- **代码部署方式**：由于 TRAE 插件不支持 `spark:app:write` scope，代码由用户手动上传到妙搭 Web 控制台
- **LLM 密钥管理**：OpenAI/Anthropic API Key 存妙搭环境变量，不硬编码
- **事件订阅回调**：妙搭云函数提供公网回调 URL，飞书事件订阅推送邮件事件到该 URL
- **认证身份**：飞书自建应用 OAuth（user_access_token），用户点同意即授权
- **飞书任务同步**：Mission/WorkItem 状态变更时同步到飞书任务，飞书任务状态变更也回调更新多维表格
- **现有代码**：`src/workbuddy/` 完全不动，飞书原生方案在 `feishu-app/` 独立实现
