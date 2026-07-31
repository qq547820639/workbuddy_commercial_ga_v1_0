# 飞书邮箱监听 + IM 通知 MVP

用飞书邮箱 REST 轮询替代 Gmail / Outlook webhook，**无需公网 IP**。后台常驻 `lark-cli mail +triage` 轮询未读收件箱，发现新邮件后批量拉取详情并调用 `lark-cli im` 发飞书 IM 交互卡片通知到指定群聊。

核心链路：

```
lark-cli mail +triage  ──JSON──▶  watch_worker  ──▶  notifier  ──lark-cli im──▶  飞书群卡片
```

## 前置条件

1. 安装 / 可用 `lark-cli`（默认用 PATH 中的 `lark-cli`，找不到则用插件内置二进制 fallback）。
2. 完成用户邮箱授权：

   ```bash
   lark-cli auth login --domain mail
   ```

3. 创建一个飞书群（或用已有群），把机器人拉入群中，拿到群 `chat_id`（`oc_` 开头）。
4. （可选，阶段 2 数据持久化）初始化多维表格 Base：

   ```bash
   python3 feishu/base_init.py
   ```

   脚本会创建一个名为 `WorkBuddy数据层` 的多维表格（含 6 张表 + 字段），并打印 `BASE_TOKEN` 与各 `*_TABLE_ID` 环境变量，复制到配置即可启用邮件归档与重启去重。

## 配置（环境变量）

| 变量 | 必填 | 默认 | 说明 |
|------|------|------|------|
| `NOTIFY_CHAT_ID` | ✅ | — | 通知目标群聊 `chat_id`（`oc_` 开头），机器人需在群内 |
| `WATCH_MAILBOX` | ❌ | `me` | `+triage` / `+messages --mailbox` 目标邮箱，`me` 表示当前授权用户 |
| `POLL_INTERVAL` | ❌ | `60` | REST 轮询间隔（秒） |
| `MAX_RECONNECT_BACKOFF` | ❌ | `60` | 指数退避上限（秒） |
| `LARK_CLI_PATH` | ❌ | 自动 | lark-cli 可执行文件路径，默认 `shutil.which` + 插件内置 fallback |
| `BASE_TOKEN` | ❌ | — | 飞书多维表格 base token（阶段 2 数据持久化，未配则纯内存去重） |
| `MAIL_TABLE_ID` | ❌ | — | 邮件归档表 `table_id`（`tbl` 开头），需与 `BASE_TOKEN` 同时配置 |

示例：

```bash
export NOTIFY_CHAT_ID=oc_xxxxxxxxxxxxxxxx
# 可选：
# export WATCH_MAILBOX=me
# export POLL_INTERVAL=60
# export MAX_RECONNECT_BACKOFF=60
# 阶段 2 数据持久化（运行 base_init.py 后填入）：
# export BASE_TOKEN=bascnxxxxxxxx
# export MAIL_TABLE_ID=tblxxxx
```

未设置 `NOTIFY_CHAT_ID` 启动会直接报错并提示如何设置。

## 启动

```bash
python feishu/watch_worker.py
```

## 行为

- 常驻运行，按 `POLL_INTERVAL` 间隔轮询未读收件箱（REST 轮询，无需公网 IP / 无需 webhook）。
- 每轮 `+triage` 拉取未读列表 → 用 `notified_ids` 集合去重 → 批量 `+messages` 拉详情 → 对每封新邮件构造一张 Card 2.0 交互卡片（主题 / 发件人 / 时间 / 正文预览）发送到 `NOTIFY_CHAT_ID`。
- 轮询异常时指数退避重试（上限 `MAX_RECONNECT_BACKOFF` 秒），成功后重置退避。
- 退出码 `3`（auth 失败 / token 过期）：打印 `lark-cli auth login --domain mail` 提示并退出，需人工 relogin。
- 收到 `SIGTERM` / `SIGINT` 时优雅停止轮询，当前 `+triage` / `+messages` 调用结束后即退出。
- 单条邮件通知失败只记日志，不会拖垮 worker。
- **数据持久化（阶段 2）**：若配置了 `BASE_TOKEN` + `MAIL_TABLE_ID`，每封邮件通知后会归档到多维表格「邮件归档」表（`message_id` / 主题 / 发件人 / 接收时间 / 正文预览 / 标签 / `processing_status=NOTIFIED`）；归档失败只记日志，不阻塞通知。
- **重启去重**：worker 启动时会从「邮件归档」表拉取最近 100 条记录的 `message_id` 预填 `notified_ids`，避免重启后对已通知邮件重复发送。未配置 Base 时回退纯内存去重（重启后 `notified_ids` 清空）。

## 文件说明

| 文件 | 作用 |
|------|------|
| `config.py` | 从环境变量加载配置（dataclass），解析 lark-cli 路径、Base token / 表 ID |
| `notifier.py` | 构造 Card 2.0 卡片并调 `lark-cli im +messages-send` 发送到群聊 |
| `watch_worker.py` | 常驻 worker：REST 轮询 `lark-cli mail +triage` / `+messages`、去重、发通知、归档到 Base |
| `base_schema.py` | 多维表格 6 张表 + 字段 schema 定义（text/select/datetime/number/checkbox） |
| `base_client.py` | 多维表格数据访问层：包装 `lark-cli base +record-upsert` / `+record-list` |
| `base_init.py` | 一次性初始化脚本：建库 + 6 张表，打印 `BASE_TOKEN` / `*_TABLE_ID` 环境变量 |

## 数据持久化（阶段 2）

阶段 2 引入飞书多维表格（Base）作为 WorkBuddy 核心域数据的持久化层，替代纯内存去重。

### 初始化

```bash
python3 feishu/base_init.py
```

脚本会创建名为 `WorkBuddy数据层` 的多维表格，包含 6 张表：

| 表 | 用途 |
|------|------|
| 邮件归档 | 归档已通知邮件（`message_id` / 主题 / 发件人 / 接收时间 / 正文预览 / 标签 / 处理状态） |
| 团队 | 团队字典（`team_key` / 名称 / 是否启用） |
| 智能体 | 智能体字典（团队 / 角色 / 名称 / 是否主理人 / 状态） |
| 任务 | 任务记录（标题 / 目标 / 状态 / 风险 / 来源 / 团队 / 主理人） |
| 工作项 | 工作项记录（任务 / 标识 / 标题 / 状态 / 负责人 / 序号） |
| 智能体运行 | 运行记录（任务 / 工作项 / 智能体 / 状态 / 开始 / 结束） |

完成后打印如下环境变量，复制到配置即可：

```
BASE_TOKEN=bascnxxxxxxxx
MAIL_TABLE_ID=tblxxxx
TEAM_TABLE_ID=tblxxxx
AGENT_TABLE_ID=tblxxxx
MISSION_TABLE_ID=tblxxxx
WORK_ITEM_TABLE_ID=tblxxxx
AGENT_RUN_TABLE_ID=tblxxxx
```

> 当前 `watch_worker` 仅使用 `BASE_TOKEN` + `MAIL_TABLE_ID`（邮件归档 + 重启去重），其余表为后续阶段预留。

### 启用条件

- 配置 `BASE_TOKEN` 与 `MAIL_TABLE_ID` 后，worker 每轮通知后会归档邮件，并在启动时预填 `notified_ids`。
- 两者任一缺失则回退纯内存去重（worker 仍可正常运行，只是重启后去重集合清空）。

## 自测 notifier

```bash
export NOTIFY_CHAT_ID=oc_xxxxxxxxxxxxxxxx
python feishu/notifier.py
```

会用一行假邮件数据走一遍卡片构造 + 发送，验证 IM 链路是否打通。
