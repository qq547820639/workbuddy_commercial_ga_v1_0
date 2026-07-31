# Checklist

## 连接器 ABC 化
- [x] `connectors/base.py` 的 `MailConnector(Protocol)` 已改为 `BaseMailConnector(ABC)`
- [x] `BaseMailConnector` 提供 `decode_state` 等通用方法模板实现（+ `__init__`）
- [x] `normalize_message` 标记为 `@abstractmethod`
- [x] `GmailConnector` 继承 `BaseMailConnector`，删除重复方法
- [x] `MicrosoftGraphConnector` 继承 `BaseMailConnector`，删除重复方法
- [x] 未实现 `normalize_message` 的子类实例化时抛 `TypeError`

## 支付适配器重命名
- [x] `services/billing/` 目录已重命名为 `services/payments/`
- [x] `get_billing_provider` 重命名为 `get_payment_provider`
- [x] `services/commercial/billing.py` 的 3 处 import 已更新
- [x] grep 全局无残留 `services.billing` 引用

## business.py 拆分
- [x] `services/_transitions.py` 包含共享 `_xxx_transition` helpers + `BusinessError` / `ConflictError`
- [x] `services/mission_service.py` 包含 mission/work-item/agent-run 生命周期 + dispatch + ingest_mail
- [x] `services/collaboration_service.py` 包含协作请求全部方法
- [x] `services/constitution_service.py` 包含章程版本流 + `_constitution_transition`（依赖本地 dict，留本文件）
- [x] `api/main.py` / `api/team_routes.py` / `beta_routes.py` / `executor.py` / `external_actions.py` / `mail_sync.py` / 3 个测试文件的 import 已指向新 service 文件（共 9 处）
- [x] `services/business.py` 保留为 re-export 兼容兜底（40 个名全覆盖）

## unit_of_work 事务边界
- [x] `db_session` 升级为 unit_of_work 语义（yield 后自动 commit，except 自动 rollback）
- [x] `api/team_routes.py` 的 8 处 `session.commit()` 已替换
- [x] `api/beta_routes.py` 的 12 处 + `api/pilot_routes.py` 的 12 处已替换
- [x] `api/commercial_routes.py` 的 32 处已替换（保留 billing_webhook 自管 session 1 处）
- [x] `api/main.py` 的 36 处已替换（保留 gmail_webhook except 块 1 处 + gmail_sync except 块 1 处 + graph_watch except 块 1 处）
- [x] grep `session.commit()` 在 `src/workbuddy/api/` 仅剩 4 处有意保留的 partial commit

## 行为不变性验证
- [x] 每个 Task 完成后 pytest 76 passed
- [x] 每个 Task 完成后 OpenAPI diff 为空
- [x] `scripts/verify.sh` 12 步全绿
- [x] 改动已提交到 origin/main（commit f2b1469）
