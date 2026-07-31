# Checklist

## 连接器 ABC 化
- [ ] `connectors/base.py` 的 `MailConnector(Protocol)` 已改为 `BaseMailConnector(ABC)`
- [ ] `BaseMailConnector` 提供 `decode_state` 等通用方法模板实现
- [ ] `normalize_message` 标记为 `@abstractmethod`
- [ ] `GmailConnector` 继承 `BaseMailConnector`，删除重复方法
- [ ] `MicrosoftGraphConnector` 继承 `BaseMailConnector`，删除重复方法
- [ ] 未实现 `normalize_message` 的子类实例化时抛 `TypeError`

## 支付适配器重命名
- [ ] `services/billing/` 目录已重命名为 `services/payments/`
- [ ] `get_billing_provider` 重命名为 `get_payment_provider`
- [ ] `services/commercial/billing.py` 的 2 处局部 import 已更新
- [ ] grep 全局无残留 `services.billing` 引用

## business.py 拆分
- [ ] `services/_transitions.py` 包含所有 `_xxx_transition` helpers + `BusinessError` / `ConflictError`
- [ ] `services/mission_service.py` 包含 mission/work-item/agent-run 生命周期 + dispatch + ingest_mail
- [ ] `services/collaboration_service.py` 包含协作请求全部方法
- [ ] `services/constitution_service.py` 包含章程版本流全部方法
- [ ] `api/main.py` / `api/team_routes.py` 等 import 已指向新 service 文件
- [ ] `services/business.py` 已删除或仅作 re-export 空壳

## unit_of_work 事务边界
- [ ] `api/deps.py` 新增 `unit_of_work` 上下文管理器依赖
- [ ] `unit_of_work` 成功时自动 commit，异常时自动 rollback
- [ ] `api/team_routes.py` 的 8 处 `session.commit()` 已替换
- [ ] `api/beta_routes.py` 的 12 处 + `api/pilot_routes.py` 的 12 处已替换
- [ ] `api/commercial_routes.py` 的 33 处已替换
- [ ] `api/main.py` 的 37 处已替换（含 try/except 路由的异常分支）
- [ ] grep `session.commit()` 在 `src/workbuddy/api/` 计数为 0

## 行为不变性验证
- [ ] 每个 Task 完成后 pytest 76 passed
- [ ] 每个 Task 完成后 OpenAPI diff 为空
- [ ] `scripts/verify.sh` 12 步全绿
- [ ] 改动已提交到 origin/main
