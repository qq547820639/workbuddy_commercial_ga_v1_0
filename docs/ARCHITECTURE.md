# WorkBuddy Production Pilot v0.4 架构

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

## 信任边界

- 身份由 JWT/OIDC Claim 决定；
- Tenant Claim 同时写入 PostgreSQL session context；
- 邮件、附件、网页、Skill 和模型输出均为不可信输入；
- ToolGrant 是任务级短期授权；
- Approval 与 ExternalOperation 分离；
- Production live send 可额外要求 PilotProgram、LIVE_SEND 邮箱以及 Gate B/C 和 Gate D 发送前证据；
- Gate Ready 由自动观察、已验证证据和责任人签署共同决定。

## 持久化核心

Mission、WorkItem、AgentRun、Approval、ExternalOperation 使用状态机。发布门使用独立对象，不通过修改 Mission 状态伪装生产就绪。

## Evidence 不可变性

证据元数据计算 SHA-256。文件写入 Filesystem 或 S3；生产要求 S3 服务端加密。签署引用当前 verified evidence set 的快照哈希，因此任何证据变化都会使原签署失效。
