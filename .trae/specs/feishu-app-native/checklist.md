# Checklist

## 飞书自建应用（OAuth 载体）
- [ ] 在飞书开放平台创建自建应用 WorkBuddy
- [ ] 申请并审批 OAuth scope：`mail:user_mailbox:readonly` / `mail:user_mailbox.message:send` / `im:message:create_by_user` / `base:record:*` / `base:app:*`
- [ ] OAuth 重定向 URL 配置为妙搭应用域名
- [ ] `app_id` 和 `app_secret` 已写入妙搭应用环境变量（`apps +env-set`）
- [ ] 用户授权流程能正确拿到 `user_access_token` 和 `refresh_token`
- [ ] token 过期能自动用 `refresh_token` 刷新

## 妙搭应用基础设施
- [x] 妙搭全栈应用代码骨架已创建（本地 `feishu-app/`，含 .spark/meta.json）
- [x] 本地仓库结构符合妙搭规范（lib/ + functions/ + pages/ + schema.sql）
- [x] `mail_archive` 表 schema 正确（message_id PK / subject / from_name / from_mail / received_at / body_preview / labels / processing_status）
- [x] `config` 表 schema 正确（config_key PK / config_value / updated_at）
- [x] `worker_status` 表 schema 正确（固定 id=1 / is_running / last_poll_at / total_notified / error_count）
- [x] `worker_log` 表 schema 正确（id 自增 / log_level / message / created_at）
- [ ] 4 张表在妙搭 dev 和 online 环境实际创建（用户手动在妙搭 Web 控制台执行 schema.sql）
- [x] `worker_status` 预填一行 `is_running=false`（schema.sql 含 INSERT）
- [x] `config` 预填默认值 `NOTIFY_CHAT_ID` / `POLL_INTERVAL` / `MAX_RECONNECT_BACKOFF`（schema.sql 含 INSERT）

## OpenAPI 客户端工具
- [x] `feishu-oauth.js` 实现 token 换取 + 自动 refresh（node --check 通过）
- [x] `feishu-mail.js` 实现 `listUnread()` 返回未读邮件 message_id 列表（node --check 通过）
- [x] `feishu-mail.js` 实现 `getMessages(ids)` 返回邮件详情（node --check 通过）
- [x] `feishu-im.js` 实现 `sendCard(chat_id, card)` 发交互卡片（node --check 通过）
- [x] `db.js` 实现 execute/queryOne/queryAll/insert/update（node --check 通过）
- [x] `logger.js` 实现 info/warn/error 写 `worker_log` 表 + 控制台打印（node --check 通过）
- [ ] 实际妙搭环境运行验证（需部署后测试）

## poll_once 云函数（核心轮询）
- [x] 函数入口 `functions/poll_once.js` 已实现（node --check 通过）
- [x] 拉未读邮件列表 → SQL 过滤已归档 message_id
- [x] 对新邮件批量拉详情 → 发 IM 卡片 → INSERT 归档
- [x] 更新 `worker_status.last_poll_at` / `total_notified`
- [x] 异常吞掉写日志，不阻断后续邮件处理
- [ ] 实际妙搭环境运行验证（需部署后测试）

## 状态与配置云函数
- [x] `get_status` 返回 is_running / last_poll_at / total_notified / 归档总数 / 最近 20 条日志
- [x] `list_archives` 支持 page/size 分页，按 received_at DESC 排序
- [x] `update_config` UPSERT 到 config 表，下次轮询立即生效
- [x] `control_worker` 更新 `worker_status.is_running`（妙搭 automation API 调用占位待验证）
- [x] `resend_notification` 按 message_id 查归档记录重发 IM 卡片
- [ ] 实际妙搭环境运行验证（需部署后测试）

## HTML 控制台
- [x] 仪表盘页（index.html）：展示运行状态 + 累计计数 + 最近日志
- [x] 归档列表页（archives.html）：分页展示，点击可展开正文预览
- [x] 配置页（config.html）：表单 → 保存调 `update_config`
- [x] 控制页（control.html）：启停按钮 + 重发按钮
- [x] 顶部导航 4 个 tab 切换正常（components/nav.html + js/api.js）
- [x] 响应式适配手机端（飞书移动端可打开）
- [x] 样式用飞书 Design 风格（主色 #3370FF），视觉风格统一
- [ ] 实际妙搭环境运行验证（需部署后测试）

## 自动触发任务
- [ ] lark-cli 升级到支持 `apps +automation-*` 的版本
- [ ] `apps +automation-create` 创建间隔 60s 触发 `poll_once` 的任务
- [ ] `automation_id` 已记录到 `config` 表
- [ ] 验证 60s 后云函数被触发（`worker_log` 有新记录）
- [ ] `+automation-disable` 暂停后 60s 不再触发
- [ ] `+automation-enable` 恢复后 60s 内重新触发

## 部署上线
- [ ] `apps +release-create` 发布线上版本
- [ ] `apps +release-get` 轮询直到 `finished`
- [ ] `apps +access-scope-set --scope tenant` 开放给企业内所有用户
- [ ] 飞书工作台已添加 WorkBuddy 应用入口
- [ ] 业务用户（非管理员）能在工作台看到并打开应用

## 数据迁移（可选）
- [ ] `scripts/migrate_from_base.js` 能拉旧 Base 记录
- [ ] 字段映射正确（message_id / subject / from_mail / received_at 等）
- [ ] 批量 INSERT 后记录数与旧 Base 一致
- [ ] 抽样比对字段值一致

## 删除旧代码
- [ ] `feishu/watch_worker.py` 已删除
- [ ] `feishu/notifier.py` 已删除
- [ ] `feishu/base_client.py` 已删除
- [ ] `feishu/base_init.py` 已删除
- [ ] `feishu/base_schema.py` 已删除
- [ ] `feishu/config.py` 已删除
- [ ] `feishu/README.md` 更新为指向妙搭应用入口的说明

## 隔离约束
- [ ] 不改动 `src/workbuddy/` 任何现有代码
- [ ] 所有新代码在 `feishu-app/` 目录（妙搭应用本地仓库）或妙搭云端

## 端到端验证
- [ ] 业务用户视角：工作台点图标 → 控制台打开 → 完成 OAuth 授权
- [ ] 配置 NOTIFY_CHAT_ID 为测试群 → 启动 worker
- [ ] 发测试邮件 → 60s 内 IM 群收到卡片 + 仪表盘计数+1 + 归档列表有新记录
- [ ] 归档列表点「重发」→ IM 群再次收到卡片
- [ ] 改 POLL_INTERVAL=10 → 60s 内观察轮询频率变化
- [ ] 点「停止」→ 60s 后不再收新邮件通知；点「启动」→ 恢复
- [ ] 关闭浏览器/关电脑 → 邮件通知仍正常到达（妙搭云端常驻）
- [ ] 现有飞书资产保留：群 `oc_716f4d...` / Base `ZYzlbTiYga...` / 表 `tblKqL7nYS5...` 不删

## 已知风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 妙搭免费版单应用云函数上限 1 个 | 无法承载 6 个独立云函数 | 评估合并为单一入口按 `action` 参数分发；或升级标准版 |
| OAuth scope 审批慢 | 阻塞 Task 1 | 提前申请，与妙搭应用开发并行 |
| 妙搭自动触发任务最小粒度限制 | 60s 轮询可能做不到 | 确认「间隔触发」支持分钟级；不支持则降到 1 分钟轮询 |
| 飞书邮箱 OpenAPI 接口未公开文档 | `feishu-mail.js` 实现受阻 | 用 lark-cli mail 的反向接口路径作参考；或继续用 lark-cli subprocess 调用（在云函数里 spawn） |
| `user_access_token` 跨用户共享问题 | 多用户场景下 token 隔离 | MVP 阶段单用户即可，后续再做多用户隔离 |
