# 飞书原生 WorkBuddy Spec

## Why

WorkBuddy 当前依赖 Gmail/Outlook 邮件连接器，实时推送依赖公网 IP 暴露 webhook（`gmail_webhook` 路由接收 Google Pub/Sub 回调，见 [main.py:499](file:///Volumes/Extra/CodeProj/workbuddy_commercial_ga_v1_0/src/workbuddy/api/main.py#L499)）。用户要用飞书全家桶重新实现 WorkBuddy，消除对公网 IP 和外部邮件服务的依赖。

**架构决策（WebSocket → REST 轮询）**：原方案用 `lark-cli mail +watch` WebSocket 长连接接收新邮件事件。实测发现 TRAE lark 插件的外部凭据模式（"credentials are provided externally"）不向 WebSocket SDK 提供 appSecret，导致 `+watch` 报错 `7104: appSecret and clientAssertionProvider cannot be nil`。因此改用 `lark-cli mail +triage` REST 轮询方案——定时拉取未读邮件列表，同样无需公网 IP（纯出站 HTTP），且完全兼容外部凭据模式。

## What Changes

### 模块映射（WorkBuddy 现有 → 飞书全家桶）

| WorkBuddy 模块 | 现有实现 | 飞书替代 | lark skill |
|---|---|---|---|
| 邮件接入 | Gmail/Outlook 连接器 + webhook（需公网 IP） | 飞书邮箱 + `+triage` REST 轮询 | lark-mail |
| 实时事件 | Pub/Sub webhook 回调 | `+triage` 定时轮询（无公网 IP，纯出站 HTTP） | lark-mail |
| 通知/交互 | REST API 前端 | 飞书 IM 机器人 + 交互卡片 | lark-im |
| 任务系统 | mission/work-item/agent-run | 飞书任务 + 多维表格追踪状态 | lark-task + lark-base |
| 审批流 | plan approval / quality gate | 飞书审批 | lark-approval |
| 数据存储 | SQLite/PostgreSQL（db/models.py） | 飞书多维表格 | lark-base |
| 章程治理 | TeamConstitutionVersion | 飞书文档 + 版本历史 | lark-doc |
| 调度 | scheduler_tick 定时 | lark-event + 飞书日历 | lark-event + lark-calendar |
| 部署 | FastAPI 服务器（需公网 IP） | lark-cli 后台进程 / 妙搭托管 | lark-shared |

### 第一阶段（本 spec 聚焦）：邮箱→IM 最小事件链路 MVP

验证核心假设：飞书邮箱 REST 轮询能替代 webhook 实现近实时邮件接入，无需公网 IP。

- `lark-cli` 通过 TRAE 插件外部凭据模式已完成用户身份授权（identity=user, tokenStatus=ready）
- 后台常驻 worker 定时调用 `lark-cli mail +triage --filter '{"folder":"inbox","is_unread":true}'` 拉取未读邮件
- 对新增未读邮件调用 `lark-cli mail +messages --message-ids <id> --html=false` 获取 body_preview
- 收到新邮件 → 解析元数据 → `lark-cli im +messages-send` 发送飞书 IM 交互卡片通知
- 新增 `feishu/` 目录存放编排脚本，与 WorkBuddy 现有 `src/` 隔离（本阶段不动现有代码）

### 后续阶段（后续独立 spec delta，本 spec 仅概述，不展开）

- **阶段 2**：多维表格数据层——把 mission/agent_run/collaboration 等模型迁移到飞书多维表格
- **阶段 3**：飞书任务映射——mission/work-item 生命周期映射到飞书任务
- **阶段 4**：飞书审批映射——plan approval / quality gate 映射到飞书审批流
- **阶段 5**：妙搭托管 + 端到端——把编排逻辑部署到妙搭云端，无需本地进程

## Impact

- Affected specs: 本 spec 为全新方向，与现有 `refactor-p1-abstraction-transactions`（Gmail/Outlook 连接器 ABC 化）形成替代关系——飞书原生方案落地后，Gmail/Outlook 连接器将逐步废弃
- Affected code:
  - 新增 `feishu/` 目录（编排脚本：watch worker + 事件处理 + 配置）
  - 第一阶段不改动 `src/workbuddy/` 任何现有代码
  - 后续阶段将逐步用飞书能力替代 `src/workbuddy/services/`、`src/workbuddy/connectors/`、`src/workbuddy/api/`

## ADDED Requirements

### Requirement: lark-cli 授权连接飞书邮箱

系统 SHALL 通过 TRAE lark 插件的外部凭据模式完成用户身份授权，identity=user，tokenStatus=ready，能访问飞书邮箱 API。

#### Scenario: 授权已就绪
- **GIVEN** TRAE lark 插件已连接并授权
- **WHEN** 执行 `lark-cli whoami --json`
- **THEN** 返回 `identity: "user"`、`tokenStatus: "ready"`、`available: true`
- **AND** `lark-cli mail user_mailboxes profile --params '{"user_mailbox_id":"me"}'` 返回 `primary_email_address`

### Requirement: 飞书邮箱 REST 轮询监听

系统 SHALL 通过 `lark-cli mail +triage --filter '{"folder":"inbox","is_unread":true}' --format data` 定时轮询未读邮件，无需公网 IP / webhook 回调。

#### Scenario: 新邮件到达
- **GIVEN** worker 后台常驻运行，每 POLL_INTERVAL 秒轮询一次
- **WHEN** 飞书邮箱收到新邮件
- **THEN** 下一次轮询返回该邮件的 `message_id` / `date` / `from` / `subject` / `labels`
- **AND** 对新增 message_id 调用 `+messages --html=false` 获取 `body_preview` / `head_from` / `internal_date`
- **AND** 整个过程不依赖公网 IP 或入站 webhook（纯出站 HTTP）

#### Scenario: 轮询稳定性
- **WHEN** 单次轮询 API 调用失败（网络错误 / token 过期）
- **THEN** worker 记录错误 + 退避重试 + 下一轮继续
- **AND** 已通知的 message_id 不重复通知（本地去重集合）

### Requirement: 飞书 IM 机器人邮件通知

系统 SHALL 在收到新邮件事件后，通过 `lark-cli im +messages-send` 向指定飞书会话发送交互卡片，含邮件主题/发件人/时间/正文摘要。

#### Scenario: 邮件通知卡片
- **GIVEN** worker 轮询发现新未读邮件，已配置目标 `chat_id`
- **WHEN** 事件处理器解析出 subject / from / message_id / body_preview
- **THEN** 调用 `lark-cli im +messages-send --as bot --chat-id <oc> --msg-type interactive --content <card_json>` 发送交互卡片
- **AND** 卡片含 subject、from、time、body_preview

### Requirement: 后台常驻 Worker 脚本

系统 SHALL 提供一个后台 worker 脚本（`feishu/watch_worker.py`），常驻运行 REST 轮询循环并处理新邮件事件，无需额外服务器部署。

#### Scenario: worker 启动
- **WHEN** 执行 `python feishu/watch_worker.py`
- **THEN** 进入轮询循环：每 POLL_INTERVAL 秒调用 `lark-cli mail +triage` 拉取未读邮件
- **AND** 对新增 message_id 调用 `+messages` 获取详情后派发给 notifier
- **AND** 收到 SIGTERM/SIGINT 时优雅退出

#### Scenario: worker 异常恢复
- **WHEN** 单次轮询失败（网络错误 / API 错误）
- **THEN** worker 记录错误 + 退避重试 + 下一轮继续
- **AND** 不丢失已通知状态（去重集合在内存中维护）

## MODIFIED Requirements

无。本 spec 为全新方向，不修改现有 WorkBuddy 需求（第一阶段不动现有代码）。

## REMOVED Requirements

无。Gmail/Outlook 连接器的废弃发生在后续阶段，届时单独 spec 处理。

## 假设与约束

- **部署形态（第一阶段）**：lark-cli 后台脚本，可在本地或任意能跑进程的环境运行，无需公网 IP；妙搭托管在阶段 5 评估
- **实现方式**：用 lark-cli（TRAE 插件内置）编排飞书能力，不引入新的飞书 SDK 依赖
- **凭据模式**：TRAE lark 插件外部凭据模式（"credentials are provided externally"），REST API 调用正常，但 WebSocket 长连接（`+watch`）因 appSecret 不可用而无法使用，改用 REST 轮询
- **轮询间隔**：默认 60 秒，可通过 `POLL_INTERVAL` 环境变量调整
- **与 WorkBuddy 现有代码关系**：第一阶段完全隔离（新增 `feishu/` 目录），不改动 `src/workbuddy/`
- **认证身份**：`--as user`（用户身份访问邮箱和发送 IM，TRAE 插件 strict mode 仅允许 user 身份，bot 身份不可用）
