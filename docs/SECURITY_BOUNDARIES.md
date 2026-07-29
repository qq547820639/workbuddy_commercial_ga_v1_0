# Security boundaries

1. Email, attachments, webpages, model output and uploaded Skill text are untrusted data, not system instructions.
2. Tenant isolation is enforced by application filtering and PostgreSQL forced RLS.
3. OAuth tokens are encrypted at rest and are never returned by mailbox APIs.
4. Read scope and send scope are granted separately for Gmail and Microsoft Graph.
5. An AgentRun only accesses the current Mission through explicit task-scoped ToolGrant records.
6. Closed, cancelled or timed-out Runs cannot invoke tools.
7. User Skill uploads are declarative; executable patterns and external-write permission escalation are rejected.
8. Model output is Schema-validated and cannot modify permissions, policies, recipients or approvals.
9. High-risk commercial, legal, date, amount, attachment and external-write actions require owner approval.
10. Approval binds exact content and Mission version; any protected change invalidates approval.
11. Deployment and tenant recipient allowlists must both permit every To/CC/BCC address.
12. BCC and attachments are disabled unless enabled at both deployment and tenant levels.
13. Live send is disabled by default and additionally constrained by daily and per-Mission limits.
14. Provider messages, webhook events and operation keys are idempotent.
15. Provider acceptance is not treated as final success until verification.
16. `UNKNOWN` results cannot be retried directly.
17. Audit events are append-only at the application layer and chained by tenant-local sequence and SHA-256.
18. The owner can pause the entire company, a team or a Mission.
19. Secrets, full Tokens and private model reasoning are excluded from normal logs and model invocation records.
20. External cloud configuration and production access require independent operator review.

21. Webhook routing is the only pre-tenant lookup and uses a minimal binding containing no mailbox content or credentials; all tenant data access occurs after forced-RLS context is set.
22. Beta readiness is evidence-based: configuration-only preflight is reported separately from a release gate proven by successful synchronization, review or verified live operation.

23. Production 使用 JWT/OIDC Claim 确定 Actor、Tenant 和 Role；请求头不能覆盖 Claim。
24. Gate 签署要求 Token 中包含对应责任角色，并绑定当前证据快照。
25. 证据文件使用 SHA-256，生产应写入启用服务端加密的 S3 兼容对象存储。
26. Production Ready 检查会拒绝 SQLite、HTTP 公网 URL、local_headers 身份和弱密钥。
27. Production Go/No-Go 不接受纯配置证明，必须观察真实同步、模型、发送和运营证据。
