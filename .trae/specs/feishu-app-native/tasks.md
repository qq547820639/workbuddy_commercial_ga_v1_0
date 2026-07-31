# Tasks

> **前置条件**：用户是飞书企业管理员（或可联系管理员），可以创建自建应用并审批 OAuth scope。妙搭免费版可用（如云函数数量不够需评估升级到标准版）。

## 阶段 3：飞书原生应用重写

### Task 1: 创建飞书自建应用 + OAuth 配置
- [ ] SubTask 1.1: 在飞书开放平台创建自建应用（应用名 `WorkBuddy`，描述「飞书邮箱监听+IM通知」）
- [ ] SubTask 1.2: 申请 OAuth scope：`mail:user_mailbox:readonly` / `mail:user_mailbox.message:send` / `im:message:create_by_user` / `base:record:*` / `base:app:*`
- [ ] SubTask 1.3: 配置 OAuth 重定向 URL 到妙搭应用域名（先占位，妙搭应用创建后回填）
- [ ] SubTask 1.4: 拿到 `app_id` 和 `app_secret`，写入妙搭应用环境变量
- [ ] SubTask 1.5: （可选）配置事件回调地址到妙搭云函数，预留未来邮件事件订阅

### Task 2: 创建妙搭全栈应用 + 数据库表
- [ ] SubTask 2.1: 用 `lark-cli apps +create --name WorkBuddy --type full_stack` 创建妙搭应用，拿 `app_id`
- [ ] SubTask 2.2: 用 `lark-cli apps +init` 初始化本地仓库到 `feishu-app/` 目录
- [ ] SubTask 2.3: 设计 `mail_archive` 表：`message_id PK / subject TEXT / from_name TEXT / from_mail TEXT / received_at DATETIME / body_preview TEXT(300) / labels TEXT / processing_status TEXT`
- [ ] SubTask 2.4: 设计 `config` 表：`key PK / value TEXT / updated_at DATETIME`
- [ ] SubTask 2.5: 设计 `worker_status` 表：`id=1 固定 / is_running BOOLEAN / last_poll_at DATETIME / total_notified INT / error_count INT`
- [ ] SubTask 2.6: 设计 `worker_log` 表：`id AUTO_INCREMENT / log_level TEXT / message TEXT / created_at DATETIME`
- [ ] SubTask 2.7: 用 `lark-cli apps +db-execute` 在 dev 环境创建 4 张表
- [ ] SubTask 2.8: 预填 `worker_status` 一行 `is_running=false` / 预填 `config` 默认 `NOTIFY_CHAT_ID=oc_716f4d911915d3e3d91a053e1a80f4a8` / `POLL_INTERVAL=60`

### Task 3: 实现飞书 OpenAPI 客户端工具模块
- [ ] SubTask 3.1: 实现 `lib/feishu-oauth.js`：用 `app_id` + `app_secret` 换 `user_access_token`，缓存到妙搭 env 变量，过期自动 refresh
- [ ] SubTask 3.2: 实现 `lib/feishu-mail.js`：调 `GET /mail/v1/mailboxes/{user_id}/messages` 拉未读邮件列表
- [ ] SubTask 3.3: 实现 `lib/feishu-mail.js` 的 `get_messages(ids)`：批量拉邮件详情
- [ ] SubTask 3.4: 实现 `lib/feishu-im.js`：调 `POST /im/v1/messages?receive_id_type=chat_id` 发交互卡片
- [ ] SubTask 3.5: 实现 `lib/db.js`：用妙搭 OpenAPI 执行 SQL（INSERT / SELECT / UPDATE）
- [ ] SubTask 3.6: 实现 `lib/logger.js`：写 `worker_log` 表 + 控制台打印

### Task 4: 实现 poll_once 云函数（核心轮询逻辑）
- [ ] SubTask 4.1: 入口 `functions/poll_once.js`：被自动触发任务调用，无入参
- [ ] SubTask 4.2: 调 `feishu-mail.list_unread()` 拉未读邮件 message_id 列表
- [ ] SubTask 4.3: SQL `SELECT message_id FROM mail_archive WHERE message_id IN (...)` 过滤已归档
- [ ] SubTask 4.4: 对新邮件调 `feishu-mail.get_messages(new_ids)` 拉详情
- [ ] SubTask 4.5: 对每封邮件调 `feishu-im.send_card(chat_id, card)` 发通知
- [ ] SubTask 4.6: 同步 `INSERT INTO mail_archive (...)` 归档
- [ ] SubTask 4.7: 更新 `worker_status` 的 `last_poll_at` 和 `total_notified += N`
- [ ] SubTask 4.8: 异常写 `worker_log` 并吞掉，不抛出
- [ ] SubTask 4.9: 单元测试：mock 飞书 OpenAPI 响应，验证去重/通知/归档/状态更新

### Task 5: 实现状态与配置云函数
- [ ] SubTask 5.1: `functions/get_status.js`：查 `worker_status` + count(`mail_archive`) + 最近 20 条 `worker_log`
- [ ] SubTask 5.2: `functions/list_archives.js`：分页查询 `mail_archive`，支持 `page` / `size` 参数
- [ ] SubTask 5.3: `functions/update_config.js`：UPSERT 到 `config` 表，下次轮询自动读新值
- [ ] SubTask 5.4: `functions/control_worker.js`：调 `lark-cli apps +automation-enable/disable` 切换自动触发任务，更新 `worker_status.is_running`
- [ ] SubTask 5.5: `functions/resend_notification.js`：按 `record_id` 查 `mail_archive`，重发 IM 卡片

### Task 6: 实现妙搭 HTML 控制台
- [ ] SubTask 6.1: 创建 `pages/index.html`（仪表盘）：调 `get_status` 展示运行状态/累计/最近日志
- [ ] SubTask 6.2: 创建 `pages/archives.html`（归档列表）：调 `list_archives` 分页展示
- [ ] SubTask 6.3: 创建 `pages/config.html`（配置表单）：加载 `config` 表 → 表单 → 保存调 `update_config`
- [ ] SubTask 6.4: 创建 `pages/control.html`（控制台）：启停按钮调 `control_worker` + 重发按钮调 `resend_notification`
- [ ] SubTask 6.5: 共用 `components/nav.html`（顶部导航 4 个 tab）+ `components/loading.html`
- [ ] SubTask 6.6: 样式用飞书 Design Tokens（参考 lark-im 卡片风格），响应式适配手机端
- [ ] SubTask 6.7: 未授权状态展示「点此授权」按钮，跳转 OAuth 流程

### Task 7: 配置自动触发任务
- [ ] SubTask 7.1: 升级 lark-cli 到支持 `apps +automation-*` 的版本（`lark-cli update`）
- [ ] SubTask 7.2: 调 `lark-cli apps +automation-create --app-id <app> --trigger-type interval --interval 60s --action invoke --function poll_once` 创建定时任务
- [ ] SubTask 7.3: 记录返回的 `automation_id` 到 `config` 表
- [ ] SubTask 7.4: 验证 60s 后云函数被触发，日志可见
- [ ] SubTask 7.5: 测试 `+automation-disable` / `+automation-enable` 启停

### Task 8: 部署上线
- [ ] SubTask 8.1: `lark-cli apps +release-create --app-id <app>` 发布线上版本
- [ ] SubTask 8.2: `lark-cli apps +release-get --release-id <id>` 轮询直到 `finished`
- [ ] SubTask 8.3: `lark-cli apps +access-scope-set --app-id <app> --scope tenant` 开放给企业内所有用户
- [ ] SubTask 8.4: 在飞书工作台添加 WorkBuddy 应用入口（管理员配置应用可见性）

### Task 9: 数据迁移（可选）
- [ ] SubTask 9.1: 写 `scripts/migrate_from_base.js`：调 `lark-cli base +record-list` 拉旧 Base 「邮件归档」表全部记录
- [ ] SubTask 9.2: 转换字段映射后批量 INSERT 到妙搭 `mail_archive` 表
- [ ] SubTask 9.3: 验证记录数一致 + 抽样字段一致

### Task 10: 删除旧 Python 代码
- [ ] SubTask 10.1: 删除 `feishu/watch_worker.py`
- [ ] SubTask 10.2: 删除 `feishu/notifier.py`
- [ ] SubTask 10.3: 删除 `feishu/base_client.py`
- [ ] SubTask 10.4: 删除 `feishu/base_init.py`
- [ ] SubTask 10.5: 删除 `feishu/base_schema.py`
- [ ] SubTask 10.6: 删除 `feishu/config.py`
- [ ] SubTask 10.7: 更新 `feishu/README.md`：指向妙搭应用入口，说明已废弃 Python 方案

### Task 11: 端到端验证
- [ ] SubTask 11.1: 业务用户视角：飞书工作台点 WorkBuddy 图标 → 控制台打开 → 完成 OAuth 授权
- [ ] SubTask 11.2: 配置 NOTIFY_CHAT_ID 为测试群 → 启动 worker
- [ ] SubTask 11.3: 发测试邮件到飞书邮箱 → 60s 内 IM 群收到卡片 + 仪表盘计数+1 + 归档列表有新记录
- [ ] SubTask 11.4: 重发邮件测试：归档列表点「重发」→ IM 群再次收到卡片
- [ ] SubTask 11.5: 改 POLL_INTERVAL=10 → 60s 内观察轮询频率变化
- [ ] SubTask 11.6: 点「停止」→ 60s 后不再收新邮件通知；点「启动」→ 恢复
- [ ] SubTask 11.7: 关闭浏览器/关电脑 → 邮件通知仍正常到达（妙搭云端常驻）

# Task Dependencies

- Task 1（自建应用 OAuth）和 Task 2（妙搭应用+DB）独立，可并行
- Task 3（OpenAPI 客户端）依赖 Task 1（拿 OAuth token）
- Task 4（poll_once）依赖 Task 2 + Task 3
- Task 5（状态配置云函数）依赖 Task 2 + Task 3
- Task 6（HTML 控制台）依赖 Task 5（要调云函数 API）
- Task 7（自动触发）依赖 Task 4 + lark-cli 升级
- Task 8（部署上线）依赖 Task 6 + Task 7
- Task 9（数据迁移）依赖 Task 2 + Task 8（线上后导入）
- Task 10（删除旧代码）在 Task 11 验证通过后执行
- Task 11（端到端）依赖 Task 8

推荐顺序：
Task 1 ‖ Task 2 → Task 3 → Task 4 ‖ Task 5 → Task 6 ‖ Task 7 → Task 8 → Task 11 → Task 10 ‖ Task 9
