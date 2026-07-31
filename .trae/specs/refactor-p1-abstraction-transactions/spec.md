# P1 重构：抽象边界与事务模型 Spec

## Why

P0（提取/删死代码/`TenantContext`）已落地并推送（commit `4512769`），回归网（pytest 76 passed + OpenAPI diff 为空）已建立。本 spec 推进 `docs/refactor-review-2026-07-31.md` 路线图的 **P1 阶段**：落实被定义却未实现的抽象（连接器 Protocol→ABC）、收敛事务边界（路由 `commit`→`unit_of_work`）、消除同名包歧义（`billing`→`payments`）、拆分 God Module（`business.py` 724 行）。

P1 与 P0 的本质区别：**P0 是纯提取零行为风险，P1 动抽象边界与事务模型，风险显著更高**——尤其 `unit_of_work` 实际影响 5 个路由文件共 102 处 `session.commit()`（报告原估 37 处仅是 `main.py` 一处，严重低估），必须在测试护航下分步推进。

## What Changes

- **连接器 ABC 化**：`connectors/base.py` 从 `MailConnector(Protocol)` 升级为 `BaseMailConnector(ABC)`，提供模板方法（OAuth state 编解码、token 刷新、HTTP 通用逻辑），`GmailConnector`/`MicrosoftGraphConnector` 继承之，`normalize_message` 设为 `@abstractmethod` 强制实现。
- **同名包重命名**：`services/billing/`（支付适配器：Stripe/Manual/tax）重命名为 `services/payments/`，与领域层 `services/commercial/billing.py` 区分；更新全局 import。
- **事务边界下沉**：引入 `unit_of_work` 上下文管理器依赖（成功自动 commit、异常自动 rollback），逐步替换 5 个路由文件共 102 处 `session.commit()`；service 层不再依赖调用方提交。
- **`business.py` 按聚合拆分**：724 行文件按天然边界拆为 `mission_service.py`（mission/work-item/agent-run 生命周期，L39-498）、`collaboration_service.py`（协作请求，L500-610）、`constitution_service.py`（章程版本流，L610-末尾）；共享 `_transition` helpers 提取到 `_transitions.py` 或保留为内部模块。
- **不改路由契约与行为**：每步用 pytest + OpenAPI diff 验证，diff 必须为空。

## Impact

- Affected specs: 专家团任务闭环（`business.py` 拆分影响 mission/collaboration/constitution service）、Skill 与 Tool 治理（连接器 ABC 不影响 tool 授权）、Commercial GA 计费（`billing→payments` 重命名）
- Affected code:
  - `src/workbuddy/connectors/base.py`：Protocol → ABC（核心改动）
  - `src/workbuddy/connectors/gmail.py` / `microsoft_graph.py`：继承基类，删重复逻辑
  - `src/workbuddy/services/billing/` → `services/payments/`：目录重命名 + 全局 import 更新（仅 `services/commercial/billing.py` 2 处局部 import）
  - `src/workbuddy/api/deps.py`：新增 `unit_of_work` 依赖
  - `src/workbuddy/api/main.py`（37 commit）/ `commercial_routes.py`（33）/ `beta_routes.py`（12）/ `pilot_routes.py`（12）/ `team_routes.py`（8）：共 102 处 `session.commit()` 替换为 `unit_of_work`
  - `src/workbuddy/services/business.py`：拆分为 3 个 service 文件 + 共享 transitions 模块
  - `tests/`：现有 76 测试作为回归网，不新增测试（P1 是结构重构，行为不变）

## ADDED Requirements

### Requirement: 连接器抽象基类强制约束

系统 SHALL 将 `connectors/base.py` 从 `MailConnector(Protocol)` 升级为 `BaseMailConnector(ABC)`，提供 OAuth 通用逻辑（state 编解码、token 刷新、HTTP 调用骨架）的模板方法实现，并将 `normalize_message` 设为 `@abstractmethod`。`GmailConnector` 与 `MicrosoftGraphConnector` SHALL 继承 `BaseMailConnector`，删除与基类重复的逻辑。

#### Scenario: 连接器继承基类
- **WHEN** 检查 `connectors/gmail.py` 与 `microsoft_graph.py` 的类定义
- **THEN** 两者均 `class XXXConnector(BaseMailConnector):`
- **AND** 两者实现 `@abstractmethod normalize_message`
- **AND** 两者不再重复 `decode_state` / `valid_access_token` 等通用方法（已上提到基类）

#### Scenario: 未实现抽象方法报错
- **WHEN** 新建连接器子类未实现 `normalize_message`
- **THEN** 实例化时 `TypeError: Can't instantiate abstract class ... with abstract method normalize_message`

#### Scenario: 行为不变
- **WHEN** 运行 pytest
- **THEN** 76 测试全绿
- **AND** OpenAPI diff 为空（路由契约不变）

### Requirement: 支付适配器包重命名

系统 SHALL 将 `services/billing/` 重命名为 `services/payments/`，更新所有 import 引用。`get_billing_provider` 重命名为 `get_payment_provider`，调用方 `services/commercial/billing.py` 的局部 import 同步更新。

#### Scenario: 重命名后 import 正确
- **WHEN** 检查 `services/commercial/billing.py`
- **THEN** `from workbuddy.services.payments import get_payment_provider`
- **AND** `from workbuddy.services.payments.tax_engine import calculate_tax`
- **AND** 旧 `services/billing/` 路径不再存在

#### Scenario: 行为不变
- **WHEN** 运行 pytest
- **THEN** 76 测试全绿
- **AND** OpenAPI diff 为空

### Requirement: 事务边界 Unit of Work

系统 SHALL 在 `api/deps.py` 引入 `unit_of_work` 上下文管理器依赖，封装"成功 commit / 异常 rollback"语义。路由层 SHALL 逐步移除显式 `session.commit()` 调用，改用 `uow: Session = Depends(unit_of_work)` 依赖自动提交。

#### Scenario: unit_of_work 自动提交
- **GIVEN** 路由使用 `uow: Session = Depends(unit_of_work)`
- **WHEN** 路由正常返回
- **THEN** `uow.commit()` 在响应后自动执行
- **AND** service 层挂载的对象持久化

#### Scenario: unit_of_work 异常回滚
- **GIVEN** 路由使用 `uow: Session = Depends(unit_of_work)`
- **WHEN** 路由抛出异常
- **THEN** `uow.rollback()` 自动执行
- **AND** 部分挂载的对象不持久化（保证原子性）

#### Scenario: 路由层无显式 commit
- **WHEN** grep `session.commit()` 在 `src/workbuddy/api/`
- **THEN** 计数为 0（全部迁移到 unit_of_work）

#### Scenario: 行为不变
- **WHEN** 运行 pytest
- **THEN** 76 测试全绿
- **AND** OpenAPI diff 为空

### Requirement: business.py 按聚合拆分

系统 SHALL 将 `services/business.py`（724 行）按聚合边界拆分为 3 个 service 文件，共享的 `_transition` helpers 提取到独立模块。拆分后 `business.py` 仅作为兼容性 re-export 入口（或直接删除，更新所有 import）。

#### Scenario: 拆分后文件结构
- **WHEN** 检查 `src/workbuddy/services/`
- **THEN** 存在 `mission_service.py`（mission/work-item/agent-run 生命周期 + ingest_mail + dispatch）
- **AND** 存在 `collaboration_service.py`（协作请求创建/接受/拒绝/完成 + artifacts）
- **AND** 存在 `constitution_service.py`（章程草稿/审核/发布版本流）
- **AND** 存在 `_transitions.py`（共享 `_mission_transition` / `_work_transition` / `_run_transition` / `_collaboration_transition` / `_constitution_transition`）

#### Scenario: import 更新
- **WHEN** 检查 `api/main.py` / `team_routes.py` 等 import
- **THEN** 从对应 service 文件导入（如 `from workbuddy.services.mission_service import accept_mission, plan_mission, ...`）

#### Scenario: 行为不变
- **WHEN** 运行 pytest
- **THEN** 76 测试全绿
- **AND** OpenAPI diff 为空

## MODIFIED Requirements

### Requirement: 专家团任务闭环
原有 mission/work-item/agent-run 生命周期逻辑集中在 `business.py`。本变更将逻辑拆分到 `mission_service.py`，行为不变，仅文件边界调整。

### Requirement: 跨专家团协作
原有协作请求逻辑在 `business.py`。本变更将逻辑迁移到 `collaboration_service.py`，行为不变。

### Requirement: 章程与工作流运行时配置
原有章程版本流逻辑在 `business.py`。本变更将逻辑迁移到 `constitution_service.py`，行为不变。

## REMOVED Requirements

无移除项。本变更保持所有功能行为不变，仅调整抽象边界、事务模型与文件组织。
