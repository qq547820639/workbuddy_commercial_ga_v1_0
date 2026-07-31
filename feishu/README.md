# WorkBuddy 飞书邮箱监听 + IM 通知

用飞书邮箱 REST 轮询替代 Gmail / Outlook webhook，**无需公网 IP**。后台常驻 `lark-cli mail +triage` 轮询未读收件箱，发现新邮件后批量拉取详情并调用 `lark-cli im` 发飞书 IM 交互卡片通知到指定群聊。

**小白用户**：双击 `install.command` 即可完成安装（自动初始化 Base + 开机自启）。

核心链路：

```
lark-cli mail +triage  ──JSON──▶  watch_worker  ──▶  notifier  ──lark-cli im──▶  飞书群卡片
                                              ──▶  base_client ──▶  飞书多维表格（配置/状态/日志/归档）
```

## 快速开始（小白用户）

### 一键安装

1. 确保已安装 TRAE（含 lark 插件）并完成飞书登录
2. 在 Finder 中双击 `feishu/install.command`
3. 按提示完成 Base 初始化和配置
4. 安装完成后自动启动，开机自启

### 安装后管理

安装后无需命令行操作，全部在**飞书多维表格**中管理：

| 多维表格表 | 用途 |
|---|---|
| 配置 | 修改 `NOTIFY_CHAT_ID`、`POLL_INTERVAL` 等配置（改完自动生效） |
| 运行状态 | 查看 `is_running`、`last_poll_at`、`total_notified`、`error_count` |
| 运行日志 | 查看最近运行日志（INFO/WARN/ERROR） |
| 邮件归档 | 查看已通知的邮件详情 |

### 管理命令（可选）

```bash
# 停止
launchctl unload ~/Library/LaunchAgents/com.workbuddy.watch.plist

# 启动
launchctl load ~/Library/LaunchAgents/com.workbuddy.watch.plist

# 查看日志
tail -f feishu/workbuddy.log
```

## 前置条件

1. 安装 TRAE（含 lark 插件），默认用 PATH 中的 `lark-cli`，找不到则用插件内置二进制 fallback。
2. 完成用户邮箱授权：

   ```bash
   lark-cli auth login --domain mail
   ```

3. 创建一个飞书群（或用已有群），把机器人拉入群中，拿到群 `chat_id`（`oc_` 开头）。

## 手动安装（开发者）

```bash
# 1. 初始化多维表格 Base（含配置/状态/日志/归档等 9 张表）
python3 feishu/base_init.py

# 2. 将输出的环境变量写入 ~/.workbuddy.env
#    BASE_TOKEN=...  MAIL_TABLE_ID=...  CONFIG_TABLE_ID=... 等

# 3. 启动 worker
python3 feishu/watch_worker.py
```

## 配置（环境变量 + Base 配置表）

环境变量优先；环境变量缺失时自动从飞书多维表格「配置」表回退读取。

| 变量 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `NOTIFY_CHAT_ID` | ✅ | — | 通知目标群聊 `chat_id`（`oc_` 开头），机器人需在群内；可从 Base 配置表读取 |
| `WATCH_MAILBOX` | ❌ | `me` | 目标邮箱，`me` 表示当前授权用户 |
| `POLL_INTERVAL` | ❌ | `60` | REST 轮询间隔（秒）；可从 Base 配置表读取 |
| `MAX_RECONNECT_BACKOFF` | ❌ | `60` | 指数退避上限（秒）；可从 Base 配置表读取 |
| `LARK_CLI_PATH` | ❌ | 自动 | lark-cli 可执行文件路径 |
| `BASE_TOKEN` | ❌ | — | 飞书多维表格 base token（启用数据持久化） |
| `MAIL_TABLE_ID` | ❌ | — | 邮件归档表 table_id |
| `CONFIG_TABLE_ID` | ❌ | — | 配置表 table_id（启用 Base 配置回退） |
| `WORKER_STATUS_TABLE_ID` | ❌ | — | 运行状态表 table_id（启用状态写入） |
| `WORKER_LOG_TABLE_ID` | ❌ | — | 运行日志表 table_id（启用日志写入） |

## 文件说明

| 文件 | 作用 |
|------|------|
| `install.command` | macOS 一键安装脚本（双击运行：初始化 Base + launchd 开机自启） |
| `config.py` | 加载配置：环境变量优先，Base 配置表回退 |
| `notifier.py` | 构造 Card 2.0 卡片并调 `lark-cli im` 发送到群聊 |
| `watch_worker.py` | 常驻 worker：REST 轮询、去重、发通知、归档、写状态/日志到 Base |
| `base_schema.py` | 多维表格 9 张表 + 字段 schema 定义 |
| `base_client.py` | 多维表格数据访问层：包装 `lark-cli base +record-upsert` / `+record-list` |
| `base_init.py` | 一次性初始化脚本：建库 + 9 张表 + 预填默认配置 |

## 多维表格表结构

| 表 | 用途 |
|------|------|
| 邮件归档 | 归档已通知邮件（message_id / 主题 / 发件人 / 接收时间 / 正文预览 / 标签 / 处理状态） |
| 配置 | 配置键值对（NOTIFY_CHAT_ID / POLL_INTERVAL / MAX_RECONNECT_BACKOFF） |
| 运行状态 | Worker 运行状态（is_running / last_poll_at / total_notified / error_count） |
| 运行日志 | 运行日志（log_level / message / created_at） |
| 团队 | 团队字典（后续阶段预留） |
| 智能体 | 智能体字典（后续阶段预留） |
| 任务 | 任务记录（后续阶段预留） |
| 工作项 | 工作项记录（后续阶段预留） |
| 智能体运行 | 运行记录（后续阶段预留） |

## 自测 notifier

```bash
export NOTIFY_CHAT_ID=oc_xxxxxxxxxxxxxxxx
python3 feishu/notifier.py
```

会用一行假邮件数据走一遍卡片构造 + 发送，验证 IM 链路是否打通。
