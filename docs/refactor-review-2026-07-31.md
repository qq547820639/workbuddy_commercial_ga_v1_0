# 代码重构审查报告 — `workbuddy_commercial_ga_v1_0`

**日期**：2026-07-31
**范围**：`src/workbuddy/`（真实源码，不含 `build/` 构建产物）
**目标**：识别结构/命名/重复/职责/耦合五类问题，给出 before→after 方案与改进点；**不改变既有功能**
**方法论**：静态走查 + 重复模式量化（行数、调用次数、导入关系），未运行测试，未改动代码

---

## 1. 执行摘要

### 整体印象
代码**功能完整、分层意图基本正确**（api / services / db / domain / connectors 分目录，service 层承担领域逻辑，route 层薄）。但存在典型的"能跑但难维护"特征：

- **入口是 God Function**：`api/main.py` 的 `create_app()` 内联了 60 个路由（602 行），同时混入了生命周期、中间件、异常处理、Gmail 同步逻辑与 `session.commit()`，单文件承担了"应用装配 + 路由 + 事务"三重职责。
- **重复是分散的而非集中的**：删除模型列表、Gmail 邮件 upsert 循环、租户依赖注入样板各出现多次。
- **抽象被定义却未落实**：`connectors/base.py` 声明了 `MailConnector` 协议，但两个连接器都没遵守；`gate_signing._signing_key()` 有注释承诺却无实现的死分支。
- **命名导致职责边界模糊**：`services/billing/`（支付适配器）与 `services/commercial/billing.py`（计费领域）同名；`business.py` 一个 689 行文件扛了 mission/work-item/agent-run/collaboration 四条生命周期。

### 主观评价
> 这是"先求功能后求整洁"的成长型代码库，不是烂尾。所有问题都可在**保持行为不变**的前提下逐步收敛——已有 14 个测试文件（test_*.py）可作为回归安全网。建议按 P0→P1→P2 分阶段重构，每步用 `pytest` + `scripts/generate_openapi.py` 前后 diff 验证。

---

## 2. 代码库地图（现状）

| 目录 | 关键文件 | 规模 | 角色 |
|------|----------|------|------|
| `api/` | `main.py`(602) `commercial_routes.py`(670) `beta/pilot/ops/team_routes.py` | 60+ 路由 | HTTP 层 |
| `services/` | `business.py`(689) `pilot.py`(488) `model_gateway.py`(320) `external_actions.py`(290) | 37 个模块 | 领域/应用服务 |
| `services/commercial/` | `billing.py`(259) `operations.py` `ga.py` `onboarding.py` `_common.py` | — | 商业化领域 |
| `services/billing/` | `base.py` `manual.py` `stripe.py` `tax_engine.py` | — | 支付适配器（未被命名为 payments） |
| `connectors/` | `base.py`(协议) `gmail.py`(310) `microsoft_graph.py`(230) | — | 邮件连接器 |
| `db/` | `models.py`(1032) `session.py` | — | ORM 模型 + 引擎 |
| `domain/` | `state_machine.py`(190) | — | 状态机 |

---

## 3. 五类问题 × 重构方案

### 3.1 结构混乱 — God Function / God Module

**问题**：`main.py::create_app()` 把"应用装配"和"全部核心路由"塞进一个 602 行函数；60 个 `@app.get/post`、37 处 `session.commit()`、19 处 `require_tenant(session, tid)` 全部内联。路由无法独立单测（必须构造整个 app），Gmail 同步/回调逻辑也堆在路由里。

**BEFORE**（节选）：
```python
def create_app(database_url=None, auto_seed=True) -> FastAPI:
    engine = make_engine(database_url)
    ...
    @app.get("/v1/missions")
    def missions(status=None, team_id=None, tid=Depends(tenant_id), session=Depends(db_session)):
        require_tenant(session, tid)
        query = select(Mission).where(Mission.tenant_id == tid)
        ...
        return [_serialize(m) for m in session.scalars(query).all()]

    @app.post("/v1/connectors/gmail/accounts/{account_id}/sync")
    def gmail_sync(account_id, ...): ...   # 40+ 行同步逻辑直接塞在路由里
    # ... 还有 55 个路由
    return app
```

**AFTER**（拆分路由到 `APIRouter` 模块，main 只做装配）：
```python
# api/core_routes.py
core_router = APIRouter(prefix="/v1", tags=["core"])

@core_router.get("/missions")
def list_missions(ctx: TenantContext = Depends()):   # 依赖注入打包了 tenant+session+actor
    return [_serialize(m) for m in ctx.session.scalars(
        select(Mission).where(Mission.tenant_id == ctx.tenant_id)).all()]

# api/gmail_routes.py  — Gmail 专属路由，复用 services/mail_sync.py 的 upsert helper
# api/main.py — 只保留装配
def create_app(...):
    app = FastAPI(...)
    register_middleware(app); register_exception_handlers(app)
    app.include_router(core_router)
    app.include_router(gmail_router)
    app.include_router(beta_router); app.include_router(pilot_router)
    app.include_router(ops_router); app.include_router(commercial_router)
    app.include_router(team_router)
    return app
```

**改进点**：
- 每个路由文件可独立 import 测单个 handler；
- Gmail 同步/`upsert` 逻辑下沉到 `services/mail_sync.py`，路由回归"薄"；
- `create_app()` 行数从 602 → <80，职责单一（装配）。

---

### 3.2 命名不规范 — 同名包 / 泛化命名

**问题 A（同名冲突）**：`services/billing/`（支付适配器：Stripe/Manual/tax）与 `services/commercial/billing.py`（计费领域：目录/订阅/用量/发票）都叫 billing。`commercial/billing.py` 仅局部 `import` 前者（`get_billing_provider`、`calculate_tax`），新人极易混淆"哪个 billing 是干嘛的"。

**BEFORE**：
```python
# services/commercial/billing.py
from workbuddy.services.billing import get_billing_provider   # 支付适配器
from workbuddy.services.billing.tax_engine import calculate_tax
# 本文件自身是"计费领域"逻辑 → 名字撞车
```

**AFTER**：适配器层重命名为 `services/payments/`（语义明确是"支付渠道"），领域层保留 `services/commercial/billing.py` 或进一步改名为 `subscriptions.py`：
```python
from workbuddy.services.payments import get_payment_provider   # 清晰：支付渠道
from workbuddy.services.payments.tax_engine import calculate_tax
```
导入语句语义从"billing 套 billing"变为"payments（渠道）被 billing（领域）使用"，依赖方向一目了然。

**问题 B（泛化命名）**：`business.py`（689 行）名字无法体现它实际是"mission + work-item + agent-run + collaboration 四条生命周期的总控"。

**AFTER**：按聚合拆包为
- `services/mission_service.py`（accept/plan/approve/start/lead_review + 状态迁移）
- `services/work_item_service.py`（start/review/update + 依赖）
- `services/agent_run_service.py`（submit/工具授权）
- `services/collaboration_service.py`（request/respond）

每个文件只持有自己聚合的 transition + audit，消除"一个文件改一处影响全栈"的风险。

**改进点**：名字即文档；import 路径能读出依赖方向；文件粒度与领域边界对齐。

---

### 3.3 重复代码 — 三处明确复制

**问题 1（完全相同的删除列表）**：`main.py` 第 385 行（`demo_reset`）与第 432 行（`privacy_delete`）逐字复制了 21 个模型的删除顺序列表。

**BEFORE**：
```python
# demo_reset 与 privacy_delete 各自写了一遍：
for model in [OperationAttempt, ToolCall, ToolGrant, ExternalOperation, ApprovalDecision,
              ApprovalRequest, QualityEvaluation, MemoryRecord, CollaborationRequest, Evidence,
              Artifact, AgentRun, WorkItemDependency, WorkItem, Mission, DispatchFeedback,
              DispatchDecision, ModelInvocation, SyncRun, ProviderWebhookEvent, MailMessage,
              AuditEvent, OutboxEvent]:
    session.execute(delete(model).where(model.tenant_id == tid))
```

**AFTER**：提取到 `services/lifecycle.py`（或 `db/operational_data.py`）：
```python
OPERATIONAL_MODELS = (OperationAttempt, ToolCall, ToolGrant, ExternalOperation, ApprovalDecision,
                      ApprovalRequest, QualityEvaluation, MemoryRecord, CollaborationRequest, Evidence,
                      Artifact, AgentRun, WorkItemDependency, WorkItem, Mission, DispatchFeedback,
                      DispatchDecision, ModelInvocation, SyncRun, ProviderWebhookEvent, MailMessage,
                      OutboxEvent)   # 注意：AuditEvent 仅 privacy_delete 删，demo_reset 不删 → 拆成两常量

def delete_operational_data(session, tenant_id, *, include_audit: bool = False) -> None:
    models = OPERATIONAL_MODELS + (AuditEvent,) if include_audit else OPERATIONAL_MODELS
    for m in models:
        session.execute(delete(m).where(m.tenant_id == tenant_id))
```
两处路由改为 `delete_operational_data(session, tid)` / `delete_operational_data(session, tid, include_audit=True)`。**注意**：原两处差异是 privacy_delete 多删 `AuditEvent`——提取时务必保留该语义差异（见上 `include_audit` 参数），否则会改变功能。

**问题 2（Gmail upsert 循环）**：`gmail_sync`（L487-493）与 `gmail_webhook`（L560-565）重复"取消息→normalize→查重→ingest→记账"循环。

**AFTER**：下沉到 `services/mail_sync.py`：
```python
def upsert_gmail_message(session, tenant_id, gmail, message_id, *, actor: str) -> tuple[int, int]:
    normalized = gmail.normalize_message(gmail.get_message(gmail.valid_access_token(session, ...), message_id))
    before = session.scalar(select(MailMessage).where(MailMessage.tenant_id == tenant_id,
                       MailMessage.provider_message_id == normalized["provider_message_id"]))
    msg = ingest_mail(session, tenant_id, normalized, actor=actor); msg.account_id = account.id
    return (0, 1) if before else (1, 0)   # (created, reused)
```
两处路由复用同一函数。

**问题 3（依赖注入样板）**：`tid = Depends(tenant_id), session = Depends(db_session), actor = Depends(actor_id)` 在 ~40 个路由重复，且 19 处再手写 `require_tenant(session, tid)`。

**AFTER**：引入组合依赖 `TenantContext`：
```python
class TenantContext:
    def __init__(self, tenant_id=Depends(tenant_id), session=Depends(db_session), actor=Depends(actor_id)):
        self.tenant_id, self.session, self.actor = tenant_id, session, actor
        require_tenant(session, tenant_id)   # 在依赖内一次性完成鉴权

@core_router.get("/missions")
def list_missions(ctx: TenantContext = Depends()): ...
```
消除每路由三参数 + 一行 `require_tenant` 的样板。

**改进点**：单点修改删除顺序/upsert 语义即可全局生效；路由签名清爽；消除"改一处忘另一处"的回归风险。

---

### 3.4 函数职责不清 — 协议定义却不落实 / 死分支

**问题 A（抽象未落实）**：`connectors/base.py` 定义了 `MailConnector` 协议（`authorization_url`/`exchange_code`/`normalize_message`），但 `GmailConnector` 与 `MicrosoftGraphConnector` **均未继承/遵守它**（grep 确认无 `base.` 引用）。两个 200-310 行连接器各自重写 OAuth 流程与消息归一化，约 50% 结构重合。

**BEFORE**：
```python
# connectors/base.py
class MailConnector(Protocol):
    def authorization_url(self, tenant_id, user_id) -> str: ...
    def exchange_code(self, code) -> dict: ...
    def normalize_message(self, raw) -> dict: ...

# connectors/gmail.py — 完全没引用 base，自成一体
class GmailConnector:
    def authorization_url(self, ...): ...
    def exchange_code(self, ...): ...
    def normalize_message(self, ...): ...
```

**AFTER**：把 `base.py` 从"仅协议"升级为"带模板方法的抽象基类"，共享 OAuth 状态编解码、token 刷新、消息归一化骨架：
```python
class BaseMailConnector(ABC):
    def authorization_url(self, tenant_id, user_id, *, enable_send=False) -> str:
        state = self._encode_state(tenant_id, user_id, enable_send)
        return f"{self.authorize_endpoint}?...&state={state}"
    @abstractmethod
    def normalize_message(self, raw) -> dict: ...   # 各渠道差异点
    # exchange_code / refresh / list / get 的通用 HTTP 逻辑下沉到这里

class GmailConnector(BaseMailConnector): ...
class MicrosoftGraphConnector(BaseMailConnector): ...
```
**改进点**：协议从"文档"变为"强制约束"（不实现 `normalize_message` 直接报错）；OAuth/HTTP 通用逻辑只写一遍；新增渠道只需实现差异方法。

**问题 B（死分支）**：`gate_signing._signing_key()`（L13-18）有 `if not settings.app_secret or startswith("local-development"): # 生产环境应换成 owner 级密钥; pass`——注释承诺了生产行为，代码却是空 `pass`，永远走 `sha256(app_secret)`。

**BEFORE**：
```python
def _signing_key() -> bytes:
    if not settings.app_secret or settings.app_secret.startswith("local-development"):
        # In production, this would be a per-owner key. For code-scope, we use the app secret.
        pass
    return hashlib.sha256(settings.app_secret.encode()).digest()
```

**AFTER**（二选一）：
- 若暂不做 owner 级密钥：**删掉死分支与空承诺注释**，保持单一实现，避免误导：
  ```python
  def _signing_key() -> bytes:
      """HMAC signing key derived from the application secret."""
      return hashlib.sha256(settings.app_secret.encode()).digest()
  ```
- 若确有规划：引入 `settings.owner_signing_key` 字段并在此处选择，让注释变成真实分支。

**改进点**：消除"看起来有生产分支其实没有"的隐患；签名密钥来源唯一可信。

---

### 3.5 耦合过高 — 事务边界落在 HTTP 层

**问题**：37 处 `session.commit()` 写在路由里，service 函数（如 `append_audit`、`ingest_mail`）往 session 挂对象却依赖调用方提交——事务边界与 HTTP 框架耦合。后果：① 同一 service 函数在同步脚本（`scripts/*.py`）与路由里提交方式不一致；② 出错时难以保证"要么全成要么全退"；③ route 既管业务又管事务，违反单一职责。

**BEFORE**（route 直接管提交）：
```python
@app.post("/v1/missions/{mid}/accept")
def accept(mid, payload, tid=Depends(tenant_id), session=Depends(db_session)):
    mission = accept_mission(session, tid, mid, payload.expected_version, actor)
    session.commit()   # 事务边界在 HTTP 层
    return _serialize(mission)
```

**AFTER**（Unit of Work 依赖自动提交）：
```python
# deps.py
@contextmanager
def unit_of_work(session: Session = Depends(db_session)):
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback(); raise

@core_router.post("/missions/{mid}/accept")
def accept(mid, payload, ctx: TenantContext = Depends(), uow: Session = Depends(unit_of_work)):
    mission = accept_mission(uow, ctx.tenant_id, mid, payload.expected_version, ctx.actor)
    return _serialize(mission)   # 提交由 uow 在成功返回后自动完成
```
**改进点**：service 层不再关心"谁提交"，路由不再写 `commit`；脚本侧复用同一 `unit_of_work` 即可保证语义一致；异常自动回滚，审计链不被半截提交污染。

> 说明：该重构改动面最大、风险最高，列为 **P1**，需先确保测试覆盖 `accept/plan/approve` 等关键路径后再动。

---

## 4. 跨领域技术债清单（顺带发现）

| 项 | 位置 | 说明 | 优先级 |
|----|------|------|--------|
| 构建产物入库 | `build/lib/workbuddy/...` | `src/` 的完整副本，已被 `.gitignore` 忽略（第 8 行）但仍在磁盘。应清理工作树避免误改 | P2(卫生) |
| Settings God Object | `settings.py` | 单 dataclass ~60 字段跨越 auth/billing/mail/model/pilot/infra | P2 |
| 单文件巨模型 | `db/models.py`(1032) | SQLAlchemy 单文件可接受；如需可按聚合拆分，但风险/收益低 | P2 |
| `models.py` 名冲突 import | `from workbuddy.db import models` vs 子模块 | 无功能问题，仅提示 | — |

---

## 5. 重构实施路线图（保持功能不变）

**铁律**：每步结束都跑 `pytest`（14 个测试文件）+ `python scripts/generate_openapi.py` 前后 diff 必须为空（路由契约不变）。任何改变行为的改动都视为重构失败。

| 阶段 | 任务 | 改动文件 | 风险 | 验证 |
|------|------|----------|------|------|
| **P0** | 提取 `OPERATIONAL_MODELS` + `delete_operational_data`（保留 AuditEvent 差异） | `main.py` → `services/lifecycle.py` | 低（纯提取） | pytest + OpenAPI diff |
| **P0** | 提取 `upsert_gmail_message` 到 `services/mail_sync.py` | `main.py` | 低 | pytest（test 含 gmail 流） |
| **P0** | 引入 `TenantContext` 依赖，替换 ~40 处样板 | `api/deps.py` + 各路由 | 低 | pytest |
| **P0** | 删除 `gate_signing._signing_key` 死分支 | `gate_signing.py` | 极低 | pytest |
| **P1** | `connectors/base.py` 升级为 `BaseMailConnector` ABC，两连接器继承 | `connectors/*` | 中 | pytest + 两渠道冒烟 |
| **P1** | `services/billing/` 重命名为 `services/payments/`，更新 import | 全局 import | 中 | pytest + grep import |
| **P1** | 引入 `unit_of_work` 依赖，移除 37 处路由 `commit` | `api/deps.py` + `main.py` + 路由 | 高 | 全量 pytest + 手动冒烟 |
| **P1** | `business.py` 按聚合拆为 4 个 service 文件 | `services/*` | 中 | pytest |
| **P2** | `main.py` 路由外移到 `core_routes.py`/`gmail_routes.py`，`create_app` 仅装配 | `api/*` | 中 | pytest + OpenAPI diff |
| **P2** | `settings.py` 拆子 dataclass（Auth/Mail/Billing/Model/Pilot） | `settings.py` | 低 | pytest |
| **P2** | 清理 `build/` 工作树产物 | 磁盘 | 极低 | `git status` 无新增 |

**建议顺序逻辑**：P0 全是"提取/去死代码"，零行为风险，先建立安全网与信心；P1 动抽象边界与事务，需测试护航；P2 是结构美化，可随业务迭代顺带做。

---

## 6. 验证策略（关键：功能不变如何保证）

1. **回归基线**：重构前先 `pytest` 全绿、存一份 `generate_openapi.py` 输出作为契约基线。
2. **逐步验证**：每完成一个 P0/P1 项立即重跑 pytest；路由类改动额外比对 OpenAPI diff。
3. **行为敏感点重点看护**：
   - `demo_reset` 与 `privacy_delete` 对 `AuditEvent` 的删/留差异（提取时易踩坑）；
   - Gmail `upsert` 的 created/reused 计数语义；
   - `unit_of_work` 回滚是否影响审计事件持久化（审计需与业务同生共死或明确分离）。
4. **不引入新功能**：本次重构禁止顺手加特性，所有 PR 标题带 `[refactor]` 前缀，Code Review 重点看 diff 是否纯搬移/提取。

---

*本报告基于静态走查，未运行测试、未修改任何文件。落地时请严格按第 5-6 节的安全网执行。*
