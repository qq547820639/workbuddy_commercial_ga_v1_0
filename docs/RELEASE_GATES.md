# Production Pilot v0.4 发布门

## Gate A — 代码与平台

本交付通过：状态机、RLS、Outbox、审计、Skill、AgentRun、模型网关、邮箱连接器、外部操作安全、Pilot Evidence 系统、JWT/OIDC 边界、对象存储适配和自动化测试。

## Gate B — 邮箱影子试点

由系统自动观察、四类已验证证据和 Product Owner / IT Admin 签署共同决定。配置 OAuth 不等于 Gate B 通过。

## Gate C — 模型与 Agent 执行

要求真实模型调用、质量评估、模型数据协议、业务评估、红队报告、Evidence 覆盖率，以及四类责任人签署。

## Gate D — 受控真实发送

要求非 Demo 的 Provider 核验成功、UNKNOWN 演练、零重复/零未审批发送证据，以及 Operations、Security、Product 三方签署。

## Production Open

要求 Gate B/C/D Ready、无开放 P0/P1、五类生产证据和五类责任人签署。`generate_go_no_go.py` 只有在全部满足时返回 0。
