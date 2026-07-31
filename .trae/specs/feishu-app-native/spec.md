# 飞书原生应用 WorkBuddy Spec（阶段 3：全量重写）

## Why

阶段 1/2 已用 Python + lark-cli 命令行跑通了「邮箱轮询 → IM 卡片 → 多维表格归档」链路，但**完全无法交付给业务用户**：
- 用户必须开终端跑 `python3 watch_worker.py`
- 必须手设环境变量 `NOTIFY_CHAT_ID` / `BASE_TOKEN` 等
- 必须本机常驻一个 Python 进程
- 改配置要改 `.env` 重启

目标用户是「完全不懂技术的业务用户」，要求**纯飞书原生、0 部署、点应用图标就用**。本阶段把整套链路重写为飞书妙搭全栈应用：前端是妙搭 HTML 控制台（飞书工作台点开），后端是妙搭云函数 + 自动触发任务（替代 watch_worker），数据存妙搭数据库，授权走飞书自建应用 OAuth。

## What Changes

### 全量重写（Python watch_worker → Node.js 妙搭云函数）

- **新增** 飞书自建应用（cli_app）：OAuth 授权载体，托管 user_access_token
  - 申请 scope：`mail:user_mailbox:readonly`、`mail:user_mailbox.message:send`、`im:message:create_by_user`、`base:record:*`、`base:app:*`
  - 配置事件回调地址（可选，预留未来邮件事件订阅）
- **新增** 妙搭全栈应用（app_xxx）：前端控制台 + 后端云函数
  - **HTML 控制台**：
    - 状态仪表盘：worker 是否在跑、最近轮询时间、已通知邮件数、归档总数
    - 归档邮件列表：分页展示（主题/发件人/时间/正文预览），可点查看详情
    - 配置表单：NOTIFY_CHAT_ID、POLL_INTERVAL、MAX_RECONNECT_BACKOFF，点保存生效
    - 控制按钮：启动/停止 worker、查看最近 20 条日志、手动重发某封邮件的通知
  - **妙搭数据库表**：
    - `mail_archive`：message_id(主键)/subject/from_name/from_mail/received_at/body_preview/labels/processing_status
    - `config`：key/value 存配置项
    - `worker_status`：单行表，记录 is_running/last_poll_at/total_notified
    - `worker_log`：最近 N 条运行日志（环形覆盖）
  - **妙搭云函数**：
    - `poll_once`：被自动触发任务调，调飞书 OpenAPI 查未读邮件 → 发 IM 卡片 → 归档到数据库
    - `get_status`：返回仪表盘所需的状态数据
    - `list_archives`：分页查询归档邮件
    - `update_config`：保存配置
    - `control_worker`：启动/停止自动触发任务（启停 worker）
    - `resend_notification`：按 record_id 重发某封邮件的 IM 通知
  - **自动触发任务**（`apps +automation-create`）：间隔触发 60s，调 `poll_once` 云函数
- **删除** 现有 Python 代码：`feishu/watch_worker.py` / `feishu/notifier.py` / `feishu/base_client.py` / `feishu/base_init.py` / `feishu/base_schema.py` / `feishu/config.py`
- **保留** `feishu/README.md`：更新为指向妙搭应用的说明

### 数据迁移（可选，可后续阶段做）

- 多维表格 `邮件归档` 表 → 妙搭数据库 `mail_archive` 表（一次性导入脚本）

## Impact

- Affected specs:
  - [feishu-native-workbuddy](file:///Volumes/Extra/CodeProj/workbuddy_commercial_ga_v1_0/.trae/specs/feishu-native-workbuddy/spec.md)（阶段 1 MVP，Python watch_worker，作废）
  - [feishu-base-data-layer](file:///Volumes/Extra/CodeProj/workbuddy_commercial_ga_v1_0/.trae/specs/feishu-base-data-layer/spec.md)（阶段 2 多维表格数据层，作废，改用妙搭数据库）
- Affected code:
  - **删除** `feishu/` 目录下所有 Python 文件（保留 README.md）
  - **新增** 妙搭应用源码仓库（在妙搭云端开发，或本地 `feishu-app/` 拉取妙搭仓库后开发）
  - 仍不改动 `src/workbuddy/` 任何现有代码（隔离约束保留）

## ADDED Requirements

### Requirement: 飞书自建应用 OAuth 授权

系统 SHALL 通过飞书自建应用提供 OAuth 授权流程，获取 `user_access_token` 并由妙搭后端托管。

#### Scenario: 用户首次授权
- **GIVEN** 用户在飞书工作台点开 WorkBuddy 应用图标
- **WHEN** 妙搭前端检测到未授权状态
- **THEN** 跳转飞书 OAuth 授权页，展示所需 scope 列表（邮箱只读、邮箱发信、IM 发消息、Base 读写）
- **AND** 用户点同意后回调到妙搭后端，保存 `user_access_token` 和 `refresh_token`
- **AND** 自动刷新过期 token（用 `refresh_token`）

#### Scenario: token 失效
- **GIVEN** `user_access_token` 过期且 `refresh_token` 仍有效
- **WHEN** 妙搭云函数调飞书 OpenAPI 收到 401
- **THEN** 自动用 `refresh_token` 换新 `user_access_token`
- **AND** 重试原请求一次

### Requirement: 妙搭 HTML 控制台

系统 SHALL 提供一个部署在飞书云端的 HTML 控制台，用户在飞书工作台点图标即可访问。

#### Scenario: 状态仪表盘
- **GIVEN** 用户已授权并打开控制台
- **WHEN** 页面加载完成
- **THEN** 调 `get_status` 云函数
- **AND** 展示：当前是否在跑、最近轮询时间、累计已通知邮件数、累计归档邮件数、错误次数

#### Scenario: 归档邮件列表
- **GIVEN** 用户在控制台点「归档邮件」标签
- **WHEN** 进入列表页
- **THEN** 调 `list_archives?page=1&size=20`
- **AND** 分页展示：主题（截断 60 字）、发件人、接收时间、处理状态标签
- **AND** 点击单条可展开正文预览（前 300 字）

#### Scenario: 修改配置
- **GIVEN** 用户在控制台点「配置」标签
- **WHEN** 修改 `NOTIFY_CHAT_ID` 或 `POLL_INTERVAL` 后点保存
- **THEN** 调 `update_config` 云函数
- **AND** 保存到 `config` 表，下次轮询立即生效（无需重启 worker）

#### Scenario: 启停 worker
- **GIVEN** 用户在控制台点「控制」标签
- **WHEN** 点「停止」按钮
- **THEN** 调 `control_worker?action=stop` 云函数
- **AND** 调 `apps +automation-disable` 暂停自动触发任务
- **AND** 仪表盘状态更新为「已停止」

### Requirement: 妙搭云函数后端

系统 SHALL 提供一组 Node.js 妙搭云函数，替代原 Python watch_worker 的全部能力。

#### Scenario: 单次轮询（poll_once）
- **GIVEN** 自动触发任务按 60s 间隔调起 `poll_once`
- **WHEN** 云函数执行
- **THEN** 调飞书 OpenAPI `GET /mail/v1/mailboxes/{user_id}/messages?filter=is_unread`
- **AND** 过滤掉 `mail_archive` 表中已存在的 `message_id`
- **AND** 对每封新邮件：调 `POST /im/v1/messages` 发交互卡片 → `INSERT INTO mail_archive`
- **AND** 更新 `worker_status` 表的 `last_poll_at` 和 `total_notified`
- **AND** 异常只记日志，不阻断后续邮件处理

#### Scenario: 查状态（get_status）
- **GIVEN** 前端调 `get_status`
- **WHEN** 云函数执行
- **THEN** 查 `worker_status` 表返回 is_running / last_poll_at / total_notified
- **AND** 查 `mail_archive` 表 count(*) 返回归档总数
- **AND** 查 `worker_log` 表返回最近 20 条日志

#### Scenario: 启停 worker（control_worker）
- **GIVEN** 前端调 `control_worker?action=stop`
- **WHEN** 云函数执行
- **THEN** 调 `lark-cli apps +automation-disable --app-id <app> --automation-id <auto>`
- **AND** 更新 `worker_status.is_running = false`
- **AND** 写日志 `worker stopped by user`

### Requirement: 妙搭数据库表结构

系统 SHALL 在妙搭应用数据库建立 4 张表承载状态、归档、配置、日志。

| 表名 | 用途 | 关键字段 |
|------|------|----------|
| `mail_archive` | 邮件归档 | message_id(PK)/subject/from_name/from_mail/received_at/body_preview/labels/processing_status |
| `config` | 配置项 | key(PK)/value/updated_at |
| `worker_status` | 运行状态（单行） | is_running/last_poll_at/total_notified/error_count |
| `worker_log` | 运行日志 | id/log_level/message/created_at |

### Requirement: 自动触发任务调度

系统 SHALL 通过妙搭自动触发任务（`apps +automation-create`）按 60s 间隔触发 `poll_once` 云函数，替代本地常驻 worker。

#### Scenario: 启用自动触发
- **GIVEN** 用户首次授权完成
- **WHEN** 妙搭后端初始化 worker
- **THEN** 调 `apps +automation-create --app-id <app> --trigger-type interval --interval 60s --action invoke --function poll_once`
- **AND** 记录 automation_id 到 `config` 表
- **AND** 更新 `worker_status.is_running = true`

#### Scenario: 暂停/恢复
- **GIVEN** 用户在控制台点「停止」或「启动」
- **WHEN** 云函数执行
- **THEN** 调 `apps +automation-disable` 或 `apps +automation-enable` 切换状态
- **AND** 同步 `worker_status.is_running`

## MODIFIED Requirements

### Requirement: 数据持久化（来自阶段 2）
**原方案**：飞书多维表格 Base 做 `邮件归档` 表，watch_worker 启动时拉 100 条 message_id 预填 `notified_ids` 做去重。
**修改后**：归档存妙搭数据库 `mail_archive` 表，去重直接用 SQL `SELECT message_id FROM mail_archive WHERE message_id IN (...)`，无需启动预填。
**Reason**：妙搭数据库 SQL 查询比多维表格 REST 调用快、稳定，前端直连无需 subprocess。
**Migration**：可选一次性导入脚本，把现有 `ZYzlbTiYgaqnEasv1tuczqjlnie` Base 的「邮件归档」表记录导入妙搭数据库。

## REMOVED Requirements

### Requirement: 本地 Python watch_worker
**Reason**：妙搭云函数 + 自动触发任务完全替代，无需本地常驻进程。
**Migration**：删除 `feishu/watch_worker.py` / `notifier.py` / `base_client.py` / `base_init.py` / `base_schema.py` / `config.py`，保留 `README.md` 改为指向妙搭应用。

### Requirement: 飞书多维表格数据层
**Reason**：妙搭数据库 SQL 比 Base REST 更适合做后端归档存储。多维表格改为「对外可见的数据视图」（可选），不再是主存储。
**Migration**：可选一次性导入脚本；不导也不影响新流程，旧 Base 数据保留只读。

## 假设与约束

- **凭据模式升级**：从 TRAE lark 插件外部凭据模式（`--as user` + lark-cli）升级为飞书自建应用 OAuth（user_access_token + 直接调 OpenAPI）
- **妙搭自动化阻塞**（2026-07-31 发现）：TRAE lark 插件外部凭据模式不支持 `spark:app:*` scope，无法用 lark-cli 自动创建/初始化/部署妙搭应用。**调整方案**：所有代码在本地 `feishu-app/` 目录按妙搭规范写好，推送到 git `sprint/default` 分支，用户手动在妙搭 Web 控制台创建应用 + 上传代码 + 配置自动触发任务 + 发布
- **妙搭版本**：免费版单应用云函数上限 1 个，可能不够（需要 poll_once / get_status / list_archives / update_config / control_worker / resend_notification 至少 6 个云函数）。如果免费版不够，需要标准版（¥1200/人/年）或合并云函数为单一入口按 `action` 参数分发
- **自动触发任务最小粒度**：妙搭「间隔触发」支持分/时/日/周/月，分钟级粒度足够（60s 轮询）
- **OAuth scope 申请**：需要企业管理员审批 scope，业务用户只是点同意
- **隔离约束保留**：不改动 `src/workbuddy/` 任何现有代码；所有新代码在 `feishu-app/` 目录
- **现有飞书资产保留**：`oc_716f4d911915d3e3d91a053e1a80f4a8` 群、`ZYzlbTiYgaqnEasv1tuczqjlnie` Base、`tblKqL7nYS5zS1fE` 表保留不删，作历史数据只读

## 用户体验目标

| 场景 | 阶段 1/2（Python） | 阶段 3（妙搭原生） |
|------|--------------------|--------------------|
| 首次安装 | 双击 .command + 手动授权 + 手设环境变量 | 飞书工作台点图标 → OAuth 同意 → 完成 |
| 日常使用 | 开终端 + 启 worker | 不用做任何事，自动在跑 |
| 改配置 | 改 .env 重启 | 控制台点表单 → 保存 |
| 查归档 | 打开多维表格 | 控制台归档列表页 |
| 收通知 | IM 卡片（不变） | IM 卡片（不变） |
| 查状态 | 看终端日志 | 控制台仪表盘 |
| 启停 | Ctrl+C | 控制台点按钮 |
