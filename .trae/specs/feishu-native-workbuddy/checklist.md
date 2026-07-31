# Checklist

## 阶段 0：授权验证
- [x] `lark-cli whoami --json` 显示 `identity:"user"`、`tokenStatus:"ready"`、`available:true`
- [x] `lark-cli mail user_mailboxes profile` 能读到飞书邮箱 `primary_email_address`（hao.pan@xqjyctsd.com）
- [x] `lark-cli mail +triage --filter '{"folder":"inbox","is_unread":true}' --format data` 返回有效 JSON（含 messages 数组）

## 阶段 1：邮箱→IM 通知 MVP
- [x] `feishu/config.py` 含 `POLL_INTERVAL`（默认 60s）配置项
- [x] `feishu/config.py` 已移除 WebSocket 专用配置（`WATCH_MSG_FORMAT`/`WATCH_FORMAT`）
- [x] `feishu/watch_worker.py` 实现轮询循环（非 WebSocket 子进程）
- [x] worker 每 `POLL_INTERVAL` 秒调用 `lark-cli mail +triage` 拉取未读邮件
- [x] worker 维护 `notified_ids` 去重集合，不重复通知同一封邮件
- [x] worker 对新增 message_id 调用 `+messages` 获取 body_preview / head_from / internal_date
- [x] worker 单次轮询失败时退避重试 + 下一轮继续
- [x] worker 收到 SIGTERM/SIGINT 时优雅退出
- [x] `feishu/notifier.py` 适配 `+messages` 返回的 `{"ok":true,"data":{"messages":[...]}}` 信封结构（_extract_message 处理裸 message dict）
- [x] 卡片含 subject / from(name+mail) / time / body_preview
- [x] 端到端：发测试邮件 → 目标 chat 收到 IM 卡片通知
- [x] 无未读邮件时 worker 正常空转（不报错、不重复通知）
- [x] 断网恢复验证：单次轮询失败时退避重试（指数退避 + 上限 max_reconnect_backoff）
- [x] 无需公网 IP 验证：纯本地环境能收到邮件事件（无入站 webhook，纯出站 HTTP REST 调用）

## 隔离约束
- [x] 第一阶段不改动 `src/workbuddy/` 任何现有代码
- [x] 所有新增文件在 `feishu/` 目录下
