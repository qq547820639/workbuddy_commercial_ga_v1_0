# Tasks

> **环境**：lark-cli 位于 TRAE 插件 `trae-remote-official:lark` 的 `bin/`，通过外部凭据模式提供认证（identity=user）。所有 lark-cli 命令遵循 [lark-shared/SKILL.md](file:///Users/panhao/.trae-cn/plugins/trae-remote-official/lark/1.0.3/skills/lark-shared/SKILL.md) 的安全规则。
>
> **架构决策**：原方案用 `mail +watch` WebSocket 长连接，实测在 TRAE 外部凭据模式下因 appSecret 不可用（错误 7104）无法工作。改用 `mail +triage` REST 轮询——纯出站 HTTP，同样无需公网 IP。

## 阶段 0：授权验证（无代码，纯验证）

- [x] Task 0: lark-cli 授权状态验证
  - [x] SubTask 0.1: 运行 `lark-cli whoami --json` 确认 `identity:"user"`、`tokenStatus:"ready"`、`available:true`
  - [x] SubTask 0.2: 运行 `lark-cli mail user_mailboxes profile --params '{"user_mailbox_id":"me"}'` 确认能读到飞书邮箱 `primary_email_address`（hao.pan@xqjyctsd.com）
  - [x] SubTask 0.3: 运行 `lark-cli mail +triage --filter '{"folder":"inbox","is_unread":true}' --max 3 --format data` 确认 REST API 可用（返回 JSON，含 messages 数组）

## 阶段 1（MVP）：邮箱→IM 通知最小链路

- [x] Task 1: 更新 `feishu/config.py` 配置
  - [x] SubTask 1.1: 新增 `POLL_INTERVAL` 配置项（默认 60 秒），控制轮询间隔
  - [x] SubTask 1.2: 移除 WebSocket 相关配置（`WATCH_MSG_FORMAT`、`WATCH_FORMAT`），保留 `WATCH_MAILBOX`、`NOTIFY_CHAT_ID`、`MAX_RECONNECT_BACKOFF`、`LARK_CLI_PATH`
  - [x] SubTask 1.3: 更新 `FeishuConfig` dataclass 与 `load_config()` 函数

- [x] Task 2: 重写 `feishu/watch_worker.py` 为 REST 轮询循环
  - [x] SubTask 2.1: 轮询循环：每 `POLL_INTERVAL` 秒调用 `lark-cli mail +triage --filter '{"folder":"inbox","is_unread":true}' --format data` 拉取未读邮件列表
  - [x] SubTask 2.2: 解析 JSON 响应，提取 `messages[]` 数组中的 `message_id`
  - [x] SubTask 2.3: 去重：维护内存中的 `notified_ids` 集合，跳过已通知的 message_id
  - [x] SubTask 2.4: 对新增 message_id 调用 `lark-cli mail +messages --message-ids <id1,id2> --html=false --format json` 获取 `body_preview` / `head_from` / `internal_date`
  - [x] SubTask 2.5: 派发给 `notifier.send_mail_notification()` 发送 IM 卡片
  - [x] SubTask 2.6: 异常恢复：单次轮询失败时记录错误 + 退避重试 + 下一轮继续
  - [x] SubTask 2.7: 优雅退出：收到 SIGTERM/SIGINT 时停止轮询循环

- [x] Task 3: 更新 `feishu/notifier.py` 适配 `+messages` 数据格式
  - [x] SubTask 3.1: `_extract_message()` 适配 `+messages` 返回的 `{"ok":true,"data":{"messages":[...]}}` 信封结构（验证：裸 message dict 已被支持，无需改动）
  - [x] SubTask 3.2: `build_card()` 使用 `head_from`（对象 `{name, mail_address}`）、`body_preview`、`internal_date`（毫秒时间戳）字段
  - [x] SubTask 3.3: IM 发送改为 `--as user`（TRAE strict mode 仅允许 user 身份，不能用 `--as bot`）

- [x] Task 4: 端到端验证
  - [x] SubTask 4.1: 启动 `python3 feishu/watch_worker.py`，向飞书邮箱发测试邮件，确认目标 chat 收到 IM 卡片通知
  - [x] 4.1a: 无未读邮件时 worker 正常空转（不报错、不重复通知）
  - [x] 4.1b: 有未读邮件时 worker 发卡片后去重（不重复通知同一封邮件）
  - [x] SubTask 4.2: 验证断网恢复：单次轮询失败时退避重试（指数退避 + 上限 max_reconnect_backoff）
  - [x] SubTask 4.3: 验证无需公网 IP：纯本地环境能收到邮件事件（无入站 webhook，纯出站 HTTP REST 调用）

## 后续阶段（独立 spec delta，本 spec 不展开）

- 阶段 2：多维表格数据层（lark-base 替代 db/models.py）
- 阶段 3：飞书任务映射（lark-task 替代 mission_service.py）
- 阶段 4：飞书审批映射（lark-approval 替代审批流）
- 阶段 5：妙搭托管（lark-apps，无需本地进程）

# Task Dependencies

- Task 0（授权验证）是所有后续 Task 的前置
- Task 1（config 更新）独立，可与 Task 0 并行
- Task 2（watch worker 重写）依赖 Task 1
- Task 3（notifier 更新）依赖 Task 1，可与 Task 2 并行
- Task 4（端到端）依赖 Task 2 + Task 3
- 推荐顺序：Task 0 → Task 1 → (Task 2 ‖ Task 3) → Task 4
