# 飞书多维表格数据层 Spec（阶段 2）

## Why

WorkBuddy 当前用 SQLAlchemy + SQLite/PostgreSQL 存储核心域数据（Mission / WorkItem / AgentRun / Team / Agent 等，见 [models.py](file:///Volumes/Extra/CodeProj/workbuddy_commercial_ga_v1_0/src/workbuddy/db/models.py)）。阶段 1 已打通"飞书邮箱 REST 轮询 → IM 卡片通知"链路，但邮件事件只在内存中去重，未持久化，重启后丢失已通知状态。

本阶段在飞书多维表格（Base）建立 WorkBuddy 核心域数据层，让邮件归档、任务追踪、执行记录持久化到飞书原生存储，为阶段 3（飞书任务映射）和阶段 4（飞书审批）提供数据基础。同样无需公网 IP，纯出站 REST 调用。

## What Changes

- 新增 `feishu/base_client.py`：封装 `lark-cli base` 命令的数据访问层（CRUD），通过 subprocess 调用 lark-cli
- 新增 `feishu/base_schema.py`：定义 Base 表结构和字段 schema（表名、字段名、字段类型）
- 新增 `feishu/base_init.py`：一次性初始化脚本，创建 Base + 所有表 + 所有字段
- 修改 `feishu/config.py`：新增 `BASE_TOKEN` 和 `MAIL_TABLE_ID` 配置项
- 修改 `feishu/watch_worker.py`：收到新邮件后，调用 base_client 将邮件归档到 Base 的"邮件归档"表
- 修改 `feishu/notifier.py`：无改动（仅消费内存中的 message dict）

### Base 表结构设计（核心域子集）

| 表名 | 对应 WorkBuddy 模型 | 关键字段 |
|------|---------------------|----------|
| 邮件归档 | MailMessage | message_id, subject, from_name, from_mail, received_at, body_preview, labels, processing_status |
| 团队 | TeamDefinition | team_key, name, active |
| 智能体 | AgentProfile | team, role_key, name, is_lead, status |
| 任务 | Mission | title, objective, status, risk_level, source_type, team, lead_agent |
| 工作项 | WorkItem | mission, item_key, title, status, assigned_agent, sequence |
| 执行记录 | AgentRun | mission, work_item, agent, status, started_at, finished_at |

> 商业化/GA 体系（PilotProgram、BillingEvent 等）不在本阶段范围。

## Impact

- Affected specs: [feishu-native-workbuddy](file:///Volumes/Extra/CodeProj/workbuddy_commercial_ga_v1_0/.trae/specs/feishu-native-workbuddy/spec.md)（阶段 1 MVP 的延续，为其补充数据持久化层）
- Affected code:
  - 新增 `feishu/base_client.py`、`feishu/base_schema.py`、`feishu/base_init.py`
  - 修改 `feishu/config.py`（新增 BASE_TOKEN / MAIL_TABLE_ID）
  - 修改 `feishu/watch_worker.py`（邮件归档到 Base）
  - 第一阶段仍不改动 `src/workbuddy/` 任何现有代码

## ADDED Requirements

### Requirement: 飞书多维表格 Base 初始化

系统 SHALL 提供一次性初始化脚本 `feishu/base_init.py`，创建一个飞书 Base 并配置所有核心域表和字段。

#### Scenario: 首次初始化
- **GIVEN** lark-cli 已通过外部凭据模式授权（identity=user）
- **WHEN** 执行 `python3 feishu/base_init.py`
- **THEN** 调用 `lark-cli base +base-create --name "WorkBuddy数据层" --table-name "邮件归档" --fields '<field-json>'` 创建 Base 和初始表
- **AND** 对其余每张表调用 `lark-cli base +table-create` + `lark-cli base +field-create` 创建表和字段
- **AND** 输出 `BASE_TOKEN` 和各 `table_id`，提示用户写入环境变量

### Requirement: 数据访问层 base_client

系统 SHALL 提供 `feishu/base_client.py`，封装 lark-cli base 命令提供 CRUD 操作。

#### Scenario: 创建记录
- **GIVEN** 已配置 BASE_TOKEN 和 table_id
- **WHEN** 调用 `base_client.create_record(table_id, fields_dict)`
- **THEN** 执行 `lark-cli base +record-upsert --base-token <token> --table-id <id> --json '<fields>'`
- **AND** 返回 `{"ok": true, "record_id": "rec_xxx"}` 或错误信封

#### Scenario: 查询记录
- **GIVEN** 已配置 BASE_TOKEN 和 table_id
- **WHEN** 调用 `base_client.list_records(table_id, filter=None, max=20)`
- **THEN** 执行 `lark-cli base +record-list --base-token <token> --table-id <id> --format data`
- **AND** 返回记录列表

#### Scenario: 按字段值搜索
- **GIVEN** 已配置 BASE_TOKEN 和 table_id
- **WHEN** 调用 `base_client.find_by_field(table_id, field_name, field_value)`
- **THEN** 执行 `lark-cli base +record-search --filter '...'`
- **AND** 返回匹配的记录列表

### Requirement: 邮件归档持久化

系统 SHALL 在 watch_worker 收到新邮件后，将邮件元数据归档到 Base 的"邮件归档"表，实现跨重启的已通知状态持久化。

#### Scenario: 新邮件归档
- **GIVEN** watch_worker 轮询发现新未读邮件
- **WHEN** 发送 IM 通知后
- **THEN** 调用 `base_client.create_record(MAIL_TABLE_ID, {message_id, subject, from_name, from_mail, received_at, body_preview, labels})`
- **AND** 归档失败只记日志，不阻断通知流程

#### Scenario: 重启后去重
- **GIVEN** watch_worker 重启，notified_ids 内存集合为空
- **WHEN** 轮询拉到已归档的未读邮件
- **THEN** 启动时从 Base 查询最近 100 条已归档邮件的 message_id，预填充 notified_ids
- **AND** 不重复通知已归档邮件

## MODIFIED Requirements

无。本 spec 为阶段 1 的增量扩展，不修改现有需求。

## REMOVED Requirements

无。

## 假设与约束

- **凭据模式**：沿用 TRAE lark 插件外部凭据模式，`--as user`，REST API 调用
- **Base Token 持久化**：Base 创建后，base_token 需手动写入环境变量 `BASE_TOKEN`（Base token 不会自动注入环境）
- **与 WorkBuddy 现有代码关系**：仍完全隔离在 `feishu/` 目录，不改动 `src/workbuddy/`
- **字段设计原则**：优先用 text / select / datetime 等基础字段类型，不使用 formula / lookup（减少复杂度）
- **去重策略**：watch_worker 启动时从 Base 拉取最近 message_id 预填充内存集合；运行中仍用内存集合去重（Base 归档是异步落盘，不阻塞通知）
