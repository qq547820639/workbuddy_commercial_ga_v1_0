# WorkBuddy 架构

WorkBuddy 分为两层：执行层负责专家团任务闭环与安全发送，商用层负责组织、计费、上线与 GA 发布门。商用层独立于 Agent 执行层。

## 执行层架构

```text
Browser / Identity-aware Proxy
        │ JWT/OIDC
        ▼
FastAPI API ─────────────── Production Pilot Gate Service
   │                         ├─ GateEvidence + object storage hash
   │                         ├─ GateAttestation snapshot binding
   │                         ├─ OperationalDrill / Incident
   │                         └─ Go / No-Go
   │
   ├─ Mail Connectors: Gmail / Microsoft Graph
   ├─ Dispatch + Lead Planner
   ├─ Agent Runtime + Model Gateway
   ├─ Skill Registry + Tool Gateway
   ├─ Approval Policy + External Operation
   └─ Audit + Transactional Outbox
        │
        ├─ PostgreSQL 16 + forced RLS
        ├─ S3-compatible evidence/artifact store
        ├─ Worker / Scheduler / Outbox Publisher
        └─ Prometheus / logs / alerts
```

### 信任边界

- 身份由 JWT/OIDC Claim 决定；
- Tenant Claim 同时写入 PostgreSQL session context；
- 邮件、附件、网页、Skill 和模型输出均为不可信输入；
- ToolGrant 是任务级短期授权；
- Approval 与 ExternalOperation 分离；
- Production live send 可额外要求 PilotProgram、LIVE_SEND 邮箱以及 Gate B/C 和 Gate D 发送前证据；
- Gate Ready 由自动观察、已验证证据和责任人签署共同决定。

### 持久化核心

Mission、WorkItem、AgentRun、Approval、ExternalOperation 使用状态机。发布门使用独立对象，不通过修改 Mission 状态伪装生产就绪。

### Evidence 不可变性

证据元数据计算 SHA-256。文件写入 Filesystem 或 S3；生产要求 S3 服务端加密。签署引用当前 verified evidence set 的快照哈希，因此任何证据变化都会使原签署失效。

## 商用层架构

商用层独立于 Agent 执行层。

```text
Organization / Users
        │
ProductPlan → TenantSubscription → Entitlements
        │                         │
        │                         ├── ModelInvocation metering
        │                         ├── AgentRun metering
        │                         └── verified live-send metering
        │
UsageRecord → Invoice Draft → OPEN → PAID / VOID
        │
CustomerOnboarding → Shadow → Agent Draft → Live Send → Completed
        │
Support / Status / Compliance / Value Metrics
        │
Production Pilot GO + Commercial/Value/GA Evidence + Attestations
        │
Commercial GA GO / NO_GO
```

### Separation of concerns

- Agent services cannot mark invoices paid.
- Billing records cannot grant external-action permission.
- A subscription quota can restrict usage, but cannot bypass approval policy.
- Legal documents are immutable versions; acceptance binds the exact hash.
- GA evidence is append-only and verified by accountable roles.
- GA GO does not replace the Production Pilot gates; it depends on them.

### Tenant isolation

All commercial entities contain `tenant_id`. Migration 0010 enables and forces PostgreSQL Row-Level Security on every commercial table. Provisioning is an administrator-only CLI because tenant creation cannot safely depend on a tenant-scoped API request.
