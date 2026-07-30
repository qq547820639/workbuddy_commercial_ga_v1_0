# WorkBuddy 文档索引

本目录包含 WorkBuddy 执行层与商用层的全部文档。按主题分类如下，每条给一句话说明。所有链接均为相对路径。

> 文档合并说明：原 `COMMERCIAL_ARCHITECTURE.md` 已并入 `ARCHITECTURE.md`；原 `GATE_EVIDENCE.md` 已并入 `RELEASE_GATES.md`；原 `PRODUCTION_PILOT_RUNBOOK.md` 已并入 `PILOT_OPERATIONS.md`；原 `CONTROLLED_BETA_COMPLETION_MATRIX.md`（与 `COMPLETION_MATRIX.md` 重复）已删除。

## 架构

- [ARCHITECTURE.md](ARCHITECTURE.md) — 执行层与商用层架构图、信任边界、职责分离与租户隔离。
- [MODEL_GATEWAY.md](MODEL_GATEWAY.md) — 模型统一网关：JSON Schema 校验、Provider 切换、预算审计与安全边界。
- [EXTERNAL_ACTION_SAFETY.md](EXTERNAL_ACTION_SAFETY.md) — 外部动作安全模型：审批绑定、`UNKNOWN` 处理与部署/租户双重许可。

## 安全与合规

- [SECURITY_BOUNDARIES.md](SECURITY_BOUNDARIES.md) — 27 条安全不变量与系统边界。
- [IDENTITY_AND_ACCESS.md](IDENTITY_AND_ACCESS.md) — JWT/OIDC 身份来源、责任人角色、UI 与密钥管理。
- [PRIVACY_RETENTION.md](PRIVACY_RETENTION.md) — 数据最小化、记忆治理与保留/删除策略。
- [COMPLIANCE_AND_LEGAL.md](COMPLIANCE_AND_LEGAL.md) — 合规文件版本化、必需文档键与组织法律工作清单。

## 发布门与验收

- [RELEASE_GATES.md](RELEASE_GATES.md) — 证据系统机制、Pilot 门（A/B/C/D/Production Open）与商用门（Commercial/Value/GA）总览。
- [GA_RELEASE_GATES.md](GA_RELEASE_GATES.md) — 商用 GA 三个门的证据项、签署角色与自动阻断条件详情。
- [ACCEPTANCE_TEST.md](ACCEPTANCE_TEST.md) — 自动化验收范围与现场 Gate B/C/D/Production 标准。
- [FINAL_VERIFICATION.md](FINAL_VERIFICATION.md) — Commercial GA v1.0 最终验证结果、覆盖范围与诚实控制。

## 商用 GA

- [BILLING_AND_METERING.md](BILLING_AND_METERING.md) — 计量事件、订阅与发票生命周期及“不得伪造”的诚实边界。
- [CUSTOMER_ONBOARDING.md](CUSTOMER_ONBOARDING.md) — 客户上线状态机与各阶段强制清单（禁止跳级）。
- [SUPPORT_SLA.md](SUPPORT_SLA.md) — P0–P3 工单首响 SLA 与服务状态事故生命周期。
- [COMMERCIAL_COMPLETION_MATRIX.md](COMMERCIAL_COMPLETION_MATRIX.md) — Commercial GA v1.0 能力完成矩阵与外部组织待办。
- [PRODUCTION_GAPS.md](PRODUCTION_GAPS.md) — 12 项生产与商用缺口的代码自动化与组织证据对照。
- [TENANT_PROVISIONING_AND_EXIT.md](TENANT_PROVISIONING_AND_EXIT.md) — 租户隔离式开通、用户管理与退出导出（不删除审计）。

## Pilot 运营

- [PILOT_OPERATIONS.md](PILOT_OPERATIONS.md) — Pilot 操作流程、日常检查清单与扩量/停止条件。
- [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) — 从 Production Pilot 推进到 Commercial GA 的 12 周实施计划。
- [COMPLETION_MATRIX.md](COMPLETION_MATRIX.md) — Production Pilot 完成矩阵（Pilot v0.4 历史快照）。

## 部署与运维

- [DEPLOYMENT.md](DEPLOYMENT.md) — 环境分级、Production 必需配置、Kubernetes、发布顺序与备份恢复。
- [CLOUD_SETUP_CHECKLIST.md](CLOUD_SETUP_CHECKLIST.md) — Google Cloud、Microsoft Entra 与云基础设施设置清单。
- [INCIDENT_RUNBOOK.md](INCIDENT_RUNBOOK.md) — P0/P1/P2 事件响应手册。

## 集成连接器

- [GMAIL_SETUP.md](GMAIL_SETUP.md) — Gmail OAuth、Pub/Sub 增量同步与发送核验设置。
- [MICROSOFT_GRAPH_SETUP.md](MICROSOFT_GRAPH_SETUP.md) — Microsoft Graph 应用注册、delta 同步与发送核验设置。

## 合规模板

> 以下模板仅为起草清单，不是获批法律文本，发布前必须经合格法律评审。

- [legal_templates/TERMS_TEMPLATE.md](legal_templates/TERMS_TEMPLATE.md) — 服务条款起草清单。
- [legal_templates/PRIVACY_TEMPLATE.md](legal_templates/PRIVACY_TEMPLATE.md) — 隐私政策起草清单。
- [legal_templates/DPA_TEMPLATE.md](legal_templates/DPA_TEMPLATE.md) — 数据处理附录起草清单。
- [legal_templates/SUBPROCESSORS_TEMPLATE.md](legal_templates/SUBPROCESSORS_TEMPLATE.md) — 子处理商登记表模板。
- [legal_templates/SECURITY_WHITEPAPER_TEMPLATE.md](legal_templates/SECURITY_WHITEPAPER_TEMPLATE.md) — 安全白皮书模板。
