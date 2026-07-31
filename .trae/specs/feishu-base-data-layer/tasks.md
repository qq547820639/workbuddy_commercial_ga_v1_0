# Tasks

> **前置条件**：阶段 1（feishu-native-workbuddy）已完成，lark-cli 外部凭据模式可用，`feishu/` 目录已存在 config.py / watch_worker.py / notifier.py。

## 阶段 2：飞书多维表格数据层

- [x] Task 1: 定义 Base 表结构（`feishu/base_schema.py`）
  - [x] SubTask 1.1: 定义 `ALL_TABLES` 列表，含 6 张表的表名和字段列表（邮件归档 / 团队 / 智能体 / 任务 / 工作项 / 执行记录）
  - [x] SubTask 1.2: 每个字段用 `{"type": "text"|"select"|"datetime"|"number"|"checkbox", "name": "字段名"}` 格式
  - [x] SubTask 1.3: 邮件归档表字段：message_id(text), subject(text), from_name(text), from_mail(text), received_at(datetime), body_preview(text), labels(text), processing_status(select: NEW/NOTIFIED/ARCHIVED)

- [x] Task 2: 实现 Base 初始化脚本（`feishu/base_init.py`）
  - [x] SubTask 2.1: 调 `lark-cli base +base-create --name "WorkBuddy数据层" --table-name "邮件归档" --fields '<json>'` 创建 Base 和初始表
  - [x] SubTask 2.2: 对其余 5 张表，逐个调 `lark-cli base +table-create --base-token <token> --name <table_name> --fields '<json>'` 创建表 + 字段
  - [x] SubTask 2.3: 从 base-create / table-create 响应中解析 base_token / table_id（优先 `data.base.base_token` / `data.table.id`）
  - [x] SubTask 2.4: 输出 `BASE_TOKEN=xxx` 和各表 `MAIL_TABLE_ID=tblxxx` 等环境变量配置提示

- [x] Task 3: 实现数据访问层（`feishu/base_client.py`）
  - [x] SubTask 3.1: `_run_lark_cli(argv)` helper：subprocess.run 调 lark-cli，带 _QUIET_ENV，返回 (code, stdout, stderr)
  - [x] SubTask 3.2: `create_record(base_token, table_id, fields: dict) -> dict`：调 `lark-cli base +record-upsert --base-token <token> --table-id <id> --json '<fields>' --as user --format json`
  - [x] SubTask 3.3: `list_records(base_token, table_id, max_records=100) -> list[dict]`：调 `lark-cli base +record-list --base-token <token> --table-id <id> --limit <n> --as user --format json`，解析 tabular 列式响应（`data.data` + `fields` + `record_id_list`）转成 `[{"record_id":..., "fields":{...}}]`
  - [x] SubTask 3.4: `find_by_field(base_token, table_id, field_name, field_value) -> list[dict]`：调 `lark-cli base +record-list --filter-json '<filter>'`（结构化精确相等查询）
  - [x] SubTask 3.5: 所有方法返回解析后的 dict/list，错误时返回 `{"ok": false, "error": ...}` 或 `[]`，不抛异常

- [x] Task 4: 更新 `feishu/config.py` 增加 Base 配置
  - [x] SubTask 4.1: 新增 `base_token: str` 字段（可选，未配置时跳过归档）
  - [x] SubTask 4.2: 新增 `mail_table_id: str` 字段（可选）
  - [x] SubTask 4.3: 环境变量 `BASE_TOKEN` 和 `MAIL_TABLE_ID` 解析

- [x] Task 5: 集成 watch_worker 与 Base
  - [x] SubTask 5.1: watch_worker 发通知后调用 `base_client.create_record` 归档邮件到 Base
  - [x] SubTask 5.2: 归档失败只记日志，不阻断通知流程
  - [x] SubTask 5.3: worker 启动时若 BASE_TOKEN 已配置，从 Base 拉取最近 100 条邮件归档记录的 message_id 预填充 notified_ids（参数名 `max_records=100`，与 base_client.list_records 签名一致）
  - [x] SubTask 5.4: BASE_TOKEN 未配置时回退到纯内存去重（向后兼容阶段 1 行为）

- [x] Task 6: 更新 `feishu/README.md`
  - [x] SubTask 6.1: 增加 Base 初始化说明（`python3 feishu/base_init.py`）
  - [x] SubTask 6.2: 环境变量表增加 `BASE_TOKEN` 和 `MAIL_TABLE_ID`
  - [x] SubTask 6.3: 更新行为说明：邮件归档持久化 + 重启去重 + 数据层表结构说明

- [x] Task 7: 端到端验证
  - [x] SubTask 7.1: 运行 `python3 feishu/base_init.py` 创建 Base，确认输出 BASE_TOKEN 和 table_id（已创建：BASE_TOKEN=ZYzlbTiYgaqnEasv1tuczqjlnie / MAIL_TABLE_ID=tblKqL7nYS5zS1fE）
  - [x] SubTask 7.2: 设置环境变量，启动 watch_worker，发测试邮件
  - [x] 7.2a: 确认 IM 卡片通知正常发送（"已通知：【E2E验证】Base归档+重启去重-..."）
  - [x] 7.2b: 确认邮件归档到 Base（`+record-list` 查到 2 条记录，message_id 与 triage 返回一致）
  - [x] 7.2c: 重启 worker，确认不重复通知已归档邮件（标记归档邮件为 UNREAD，重启后 triage 返回 1 unread, 0 new — 被 notified_ids 过滤掉）
  - [x] SubTask 7.3: 验证 BASE_TOKEN 未配置时向后兼容（"Base 未配置，使用纯内存去重"，worker 正常运行无报错）

# Task Dependencies

- Task 1（schema 定义）是 Task 2 的前置
- Task 2（base_init）是 Task 7.1 的前置
- Task 3（base_client）独立，可与 Task 2 并行
- Task 4（config）独立，可与 Task 2/3 并行
- Task 5（watch_worker 集成）依赖 Task 3 + Task 4
- Task 6（README）依赖 Task 2 + Task 4
- Task 7（端到端）依赖 Task 2 + Task 3 + Task 4 + Task 5
- 推荐顺序：Task 1 → (Task 2 ‖ Task 3 ‖ Task 4) → Task 5 → (Task 6 ‖ Task 7)

# 实施记录

- **关键 bug 修复 1**：`base_client.list_records` 参数名 `max` 与 Python 内置函数冲突，watch_worker 调用处传 `max=100` 实际未传到 lark-cli。改为 `max_records=100`，调用处同步更新。
- **关键 bug 修复 2**：`base_client._extract_records` 原本期望 `{"items":[{"record_id":...,"fields":{...}}]}` 形态，但 `+record-list` / `+record-get` 实际返回列式 tabular 结构（`data.data` 二维数组 + `fields` 字段名数组 + `record_id_list` 数组）。重写为 zip 行值与字段名构造记录 dict，导致 `list_records` 一直返回 `[]`，重启去重失效。
- **message_id 一致性确认**：飞书邮箱 API 返回的 message_id 是 base64 编码字符串（如 `ZjFCSjdydmV0R3pxRURGQnlpbnhrK2JZUnA4PQ==`），写入 Base 后读回值完全一致（lark-cli 不会在读写过程中二次编码），去重匹配可靠。
