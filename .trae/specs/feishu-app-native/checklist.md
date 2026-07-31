# Checklist

## 飞书自建应用（OAuth 载体）
- [ ] 在飞书开放平台创建自建应用 WorkBuddy
- [ ] 申请并审批 OAuth scope：`mail:user_mailbox:readonly` / `mail:user_mailbox.message:send` / `im:message:create_by_user` / `base:record:*` / `base:app:*`
- [ ] OAuth 重定向 URL 配置为妙搭应用域名
- [ ] `app_id` 和 `app_secret` 已写入妙搭应用环境变量（`apps +env-set`）
- [ ] 用户授权流程能正确拿到 `user_access_token` 和 `refresh_token`
- [ ] token 过期能自动用 `refresh_token` 刷新

## 妙搭应用基础设施
- [ ] 妙搭全栈应用已创建（`apps +create` 返回 `app_id`）
- [ ] 本地仓库已初始化（`apps +init` 拉到 `feishu-app/` 目录）
- [ ] `mail_archive` 表结构正确（message_id PK / subject / from_name / from_mail / received_at / body_preview / labels / processing_status）
- [ ] `config` 表结构正确（key PK / value / updated_at）
- [ ] `worker_status` 表结构正确（固定 id=1 / is_running / last_poll_at / total_notified / error_count）
- [ ] `worker_log` 表结构正确（id 自增 / log_level / message / created_at）
- [ ] 4 张表在 dev 和 online 环境都已创建（`apps +db-env-migrate`）
- [ ] `worker_status` 预填一行 `is_running=false`
- [ ] `config` 预填默认值 `NOTIFY_CHAT_ID=oc_716f4d911915d3e3d91a053e1a80f4a8` / `POLL_INTERVAL=60`

## OpenAPI 客户端工具
- [ ] `feishu-oauth.js` 能换 token + 自动 refresh
- [ ] `feishu-mail.js` 的 `list_unread()` 返回未读邮件 message_id 列表
- [ ] `feishu-mail.js` 的 `get_messages(ids)` 返回邮件详情
- [ ] `feishu-im.js` 的 `send_card(chat_id, card)` 能发交互卡片
- [ ] `db.js` 能执行 INSERT / SELECT / UPDATE SQL
- [ ] `logger.js` 能写 `worker_log` 表 + 控制台打印

## poll_once 云函数（核心轮询）
- [ ] 函数入口 `functions/poll_once.js` 可被自动触发任务调用
- [ ] 拉未读邮件列表 → SQL 过滤已归档 message_id
- [ ] 对新邮件批量拉详情 → 发 IM 卡片 → INSERT 归档
- [ ] 更新 `worker_status.last_poll_at` / `total_notified`
- [ ] 异常吞掉写日志，不阻断后续邮件处理
- [ ] 单元测试：mock 飞书 OpenAPI 响应，覆盖去重/通知/归档/状态更新

## 状态与配置云函数
- [ ] `get_status` 返回 is_running / last_poll_at / total_notified / 归档总数 / 最近 20 条日志
- [ ] `list_archives` 支持 page/size 分页，按 received_at DESC 排序
- [ ] `update_config` UPSERT 到 config 表，下次轮询立即生效
- [ ] `control_worker` 能调 `apps +automation-enable/disable` 切换状态 + 同步 `worker_status.is_running`
- [ ] `resend_notification` 按 record_id 查归档记录重发 IM 卡片

## HTML 控制台
- [ ] 仪表盘页：展示运行状态 + 累计计数 + 最近日志
- [ ] 归档列表页：分页展示，点击可展开正文预览
- [ ] 配置页：加载 config → 表单 → 保存调 `update_config`
- [ ] 控制页：启停按钮 + 重发按钮
- [ ] 顶部导航 4 个 tab 切换正常
- [ ] 未授权状态展示「点此授权」按钮
- [ ] 响应式适配手机端（飞书移动端可打开）
- [ ] 样式用飞书 Design Tokens，视觉风格统一

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
