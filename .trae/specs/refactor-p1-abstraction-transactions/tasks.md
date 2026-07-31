# Tasks

> **铁律**：每个 Task 完成后立即跑 `pytest -q`（必须 76 passed）+ `PYTHONPATH=src python scripts/generate_openapi.py` 后 diff `api/openapi.yaml`（必须为空）。任何破坏行为的改动视为该 Task 失败，必须回退。环境：`.venv/bin/python`（已建好 3.11 环境）。

## 阶段 1：连接器 ABC 化（风险：中）

- [x] Task 1: `connectors/base.py` 升级为 `BaseMailConnector(ABC)`
  - [x] SubTask 1.1: 将 `MailConnector(Protocol)` 改为 `BaseMailConnector(ABC)`，把 `decode_state`（jwt 编解码通用逻辑）上提为基类方法，`normalize_message` 标记 `@abstractmethod`
  - [x] SubTask 1.2: `GmailConnector` 继承 `BaseMailConnector`，删除与基类重复的 `decode_state` 等方法
  - [x] SubTask 1.3: `MicrosoftGraphConnector` 继承 `BaseMailConnector`，删除与基类重复的方法
  - [x] SubTask 1.4: 验证 pytest 76 passed + OpenAPI diff 为空

## 阶段 2：支付适配器重命名（风险：中，影响面小）

- [x] Task 2: `services/billing/` → `services/payments/`
  - [x] SubTask 2.1: `git mv src/workbuddy/services/billing src/workbuddy/services/payments`
  - [x] SubTask 2.2: 在 `services/payments/__init__.py` 将 `get_billing_provider` 重命名为 `get_payment_provider`（保留旧名别名 `get_billing_provider = get_payment_provider` 避免遗漏，待验证后移除）
  - [x] SubTask 2.3: 更新 `services/commercial/billing.py` 两处局部 import（L160 `from workbuddy.services.payments.tax_engine import calculate_tax`，L202 `from workbuddy.services.payments import get_payment_provider`）
  - [x] SubTask 2.4: grep 全局确认无残留 `services.billing` 引用；验证 pytest 76 passed + OpenAPI diff 为空

## 阶段 3：business.py 按聚合拆分（风险：中，纯搬移）

- [x] Task 3: 拆分 `business.py` 为 3 个 service 文件 + 共享 transitions
  - [x] SubTask 3.1: 新建 `services/_transitions.py`，迁移 `_mission_transition` / `_work_transition` / `_run_transition` / `_collaboration_transition` / 及依赖的 `BusinessError` / `ConflictError`（`_constitution_transition` 留 constitution_service 内，依赖本地 dict）
  - [x] SubTask 3.2: 新建 `services/mission_service.py`，迁移 mission/work-item/agent-run 生命周期全部函数
  - [x] SubTask 3.3: 新建 `services/collaboration_service.py`，迁移协作请求全部方法
  - [x] SubTask 3.4: 新建 `services/constitution_service.py`，迁移章程版本流 + `_constitution_transition` + `CONSTITUTION_TRANSITIONS`
  - [x] SubTask 3.5: 更新 `api/main.py` / `api/team_routes.py` / `beta_routes.py` / `executor.py` / `external_actions.py` / `mail_sync.py` / 3 个测试文件的 import 指向新 service 文件（共 9 处）
  - [x] SubTask 3.6: `services/business.py` 保留为 re-export 兼容兜底（40 个名全覆盖）；验证 pytest 76 passed + OpenAPI diff 为空

## 阶段 4：引入 unit_of_work 依赖（风险：高，影响 102 处 commit）

- [x] Task 4: 新增 `unit_of_work` 依赖并替换路由层 `session.commit()`
  - [x] SubTask 4.1: `db_session` 升级为 unit_of_work 语义（yield 后自动 commit，except 自动 rollback）——不新增独立函数，最小改动
  - [x] SubTask 4.2: 删除 `api/team_routes.py` 的 8 处 + `api/beta_routes.py` 的 12 处 + `api/pilot_routes.py` 的 12 处显式 commit
  - [x] SubTask 4.3: 删除 `api/commercial_routes.py` 的 32 处（保留 billing_webhook 自管 session 的 1 处）
  - [x] SubTask 4.4: 删除 `api/main.py` 的 36 处（保留 gmail_webhook except 块 1 处）
  - [x] SubTask 4.5: 修复 2 处 except 块 partial commit 被误删（gmail_sync + graph_watch，需持久化失败状态）
  - [x] SubTask 4.6: grep 确认 `src/workbuddy/api/` 下 `session.commit()` 仅剩 4 处有意保留（gmail_webhook + gmail_sync except + graph_watch except + billing_webhook 自管 session）；验证 pytest 76 passed + OpenAPI diff 为空

## 阶段 5：最终验证与提交

- [x] Task 5: 全量验证与提交
  - [x] SubTask 5.1: 运行 `PATH="$PWD/.venv/bin:$PATH" bash scripts/verify.sh` 确认 12 步全绿
  - [x] SubTask 5.2: 提交所有改动到 origin/main（commit f2b1469）

# Task Dependencies

- Task 2（billing→payments）独立，可与 Task 1（连接器 ABC）并行
- Task 3（business.py 拆分）独立，可与 Task 1、Task 2 并行
- Task 4（unit_of_work）依赖 Task 3 完成（business.py 拆分后 import 已稳定，避免合并冲突）
- Task 5 依赖 Task 1-4 全部完成
- 推荐执行顺序：Task 2（最小风险）→ Task 1 → Task 3 → Task 4 → Task 5
