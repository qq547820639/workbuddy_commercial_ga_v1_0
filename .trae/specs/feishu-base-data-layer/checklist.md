# Checklist

## Base 表结构定义
- [x] `feishu/base_schema.py` 定义 6 张表（邮件归档 / 团队 / 智能体 / 任务 / 工作项 / 执行记录）
- [x] 邮件归档表含 message_id / subject / from_name / from_mail / received_at / body_preview / labels / processing_status 字段
- [x] 字段类型仅用 text / select / datetime / number / checkbox（不用 formula / lookup）

## Base 初始化脚本
- [x] `feishu/base_init.py` 能创建 Base "WorkBuddy数据层" + 初始表"邮件归档"
- [x] 脚本能创建其余 5 张表（团队 / 智能体 / 任务 / 工作项 / 执行记录）
- [x] 脚本能为每张表创建所有字段（通过 `--fields` JSON 数组一次性传入）
- [x] 脚本输出 BASE_TOKEN 和各 table_id 环境变量配置提示
- [x] 实际运行验证：已创建 Base（BASE_TOKEN=ZYzlbTiYgaqnEasv1tuczqjlnie / MAIL_TABLE_ID=tblKqL7nYS5zS1fE）

## 数据访问层
- [x] `feishu/base_client.py` 提供 `create_record(base_token, table_id, fields)` 方法
- [x] `feishu/base_client.py` 提供 `list_records(base_token, table_id, max_records)` 方法
- [x] `feishu/base_client.py` 提供 `find_by_field(base_token, table_id, field_name, field_value)` 方法
- [x] 所有方法错误时返回 `{"ok": false}` 或 `[]` 不抛异常
- [x] 使用 `--as user` 和 `_QUIET_ENV` 保证干净 JSON 输出
- [x] `_extract_records` 正确解析 `+record-list` / `+record-get` 的列式 tabular 响应（`data.data` + `fields` + `record_id_list`）

## config 配置
- [x] `feishu/config.py` 新增 `base_token` 和 `mail_table_id` 字段（均可选）
- [x] 环境变量 `BASE_TOKEN` / `MAIL_TABLE_ID` 解析正确

## watch_worker 集成
- [x] 发通知后归档邮件到 Base（base_client.create_record）
- [x] 归档失败只记日志不阻断通知
- [x] worker 启动时从 Base 预填充 notified_ids（若 BASE_TOKEN 已配置）
- [x] BASE_TOKEN 未配置时回退纯内存去重（向后兼容）
- [x] 调用 `base_client.list_records` 时使用 `max_records=100`（与函数签名一致，不与 Python 内置 `max` 冲突）

## 隔离约束
- [x] 不改动 `src/workbuddy/` 任何现有代码
- [x] 所有新增文件在 `feishu/` 目录下

## 端到端验证
- [x] `python3 feishu/base_init.py` 成功创建 Base 并输出 token/table_id
- [x] 启动 worker + 发测试邮件 → IM 卡片通知正常（"已通知：【E2E验证】..."）
- [x] 邮件归档到 Base（record-list 查到 2 条记录，message_id 与 triage 返回一致）
- [x] 重启 worker → 不重复通知已归档邮件（标记归档邮件为 UNREAD 后重启，triage 返回 1 unread, 0 new）
- [x] BASE_TOKEN 未配置 → 纯内存去重，不报错（向后兼容）

## 已知工作特性（非缺陷）
- `lark-cli mail +messages` 拉取邮件详情时会标记邮件为已读（label UNREAD 被清除）。这意味着新邮件被 worker 处理一次后即转为已读状态，下一轮 triage 不再返回；归档去重只在 worker 重启后才会真正生效（避免重启后对已处理但仍是未读的邮件重复通知）。
- 飞书邮箱 API 返回的 message_id 是 base64 编码字符串，写入 Base 后读回值完全一致，去重匹配可靠。
